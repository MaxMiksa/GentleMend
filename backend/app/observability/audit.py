"""
浅愈(GentleMend) — 审计中间件

功能:
  - FastAPI 依赖注入式审计记录
  - 自动捕获 who/what/when/target
  - old_value/new_value 自动 diff
  - 与业务事务同一提交（保证一致性）
  - HMAC-SHA256 数字签名防篡改
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response
from fastapi import Depends

from app.db.base import get_session
from app.models.models import ActorType, AuditLog

# ============================================================
# 审计上下文（ContextVar 线程安全）
# ============================================================

_audit_actor: ContextVar[tuple[str, ActorType] | None] = ContextVar(
    "_audit_actor", default=None,
)
_audit_request_id: ContextVar[str] = ContextVar(
    "_audit_request_id", default="",
)

# HMAC 密钥（生产环境从 Vault/环境变量加载）
AUDIT_HMAC_KEY = b"gentlemend-audit-hmac-key-change-in-production"


def set_audit_context(
    actor_id: str,
    actor_type: ActorType,
    request_id: str = "",
) -> None:
    """在请求入口设置审计上下文"""
    _audit_actor.set((actor_id, actor_type))
    _audit_request_id.set(request_id)


# ============================================================
# Diff 工具
# ============================================================

def compute_diff(
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    计算 old_value / new_value 的精简 diff。
    只保留变化的字段，减少存储开销。
    """
    if old is None or new is None:
        return old, new

    old_diff: dict[str, Any] = {}
    new_diff: dict[str, Any] = {}

    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            old_diff[key] = old_val
            new_diff[key] = new_val

    return (old_diff or None), (new_diff or None)


# ============================================================
# HMAC 签名
# ============================================================

def sign_audit_record(record: dict[str, Any]) -> str:
    """
    对审计记录生成 HMAC-SHA256 签名。
    签名内容: id + event_type + entity_type + entity_id + created_at
    """
    payload = (
        f"{record.get('id', '')}|"
        f"{record.get('event_type', '')}|"
        f"{record.get('entity_type', '')}|"
        f"{record.get('entity_id', '')}|"
        f"{record.get('created_at', '')}"
    )
    return hmac.new(
        AUDIT_HMAC_KEY, payload.encode(), hashlib.sha256,
    ).hexdigest()


def verify_signature(record: dict[str, Any], signature: str) -> bool:
    """验证审计记录签名"""
    expected = sign_audit_record(record)
    return hmac.compare_digest(expected, signature)


# ============================================================
# AuditLogger — 核心审计写入器
# ============================================================

class AuditLogger:
    """
    审计日志写入器。

    使用方式（在业务代码中）:
        audit = AuditLogger(session)
        await audit.log(
            event_type="assessment.created",
            entity_type="assessment",
            entity_id=str(assessment.id),
            new_value=assessment_dict,
        )
        # session.commit() 时审计记录一起提交

    设计要点:
      - 与业务 session 共享事务，保证原子性
      - 自动从 ContextVar 获取 actor 信息
      - 自动生成 HMAC 签名写入 metadata
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        写入一条审计记录（与业务事务同一 session）。

        Returns:
            插入的审计记录 BIGSERIAL id
        """
        # 自动 diff
        old_diff, new_diff = compute_diff(old_value, new_value)

        # 从 ContextVar 获取 actor
        actor = _audit_actor.get()
        actor_id = actor[0] if actor else None
        actor_type = actor[1] if actor else None
        request_id = _audit_request_id.get()

        event_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        record = {
            "event_id": event_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "old_value": old_diff,
            "new_value": new_diff,
            "created_at": now,
        }

        # 生成 HMAC 签名，存入 metadata
        sig_input = {**record, "id": "pending"}
        signature = sign_audit_record(sig_input)
        meta = {
            **(metadata or {}),
            "request_id": request_id,
            "hmac_sha256": signature,
        }
        record["metadata"] = meta

        result = await self._session.execute(
            insert(AuditLog).values(**record).returning(AuditLog.id),
        )
        audit_id = result.scalar_one()

        return audit_id

    async def log_create(
        self,
        entity_type: str,
        entity_id: str,
        new_value: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """记录创建操作"""
        return await self.log(
            event_type=f"{entity_type}.created",
            entity_type=entity_type,
            entity_id=entity_id,
            new_value=new_value,
            metadata=metadata,
        )

    async def log_update(
        self,
        entity_type: str,
        entity_id: str,
        old_value: dict[str, Any],
        new_value: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """记录更新操作"""
        return await self.log(
            event_type=f"{entity_type}.updated",
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
        )


# ============================================================
# FastAPI 中间件：自动设置审计上下文
# ============================================================


class AuditContextMiddleware(BaseHTTPMiddleware):
    """
    在每个请求开始时自动设置审计上下文。

    从请求头/认证信息中提取 actor_id 和 actor_type，
    生成 request_id，写入 ContextVar。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        # 生成唯一 request_id
        request_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4()),
        )
        request.state.request_id = request_id

        # 从认证头提取 actor（MVP 阶段简化处理）
        actor_id = request.headers.get("X-Actor-ID", "anonymous")
        actor_type_str = request.headers.get("X-Actor-Type", "patient")
        try:
            actor_type = ActorType(actor_type_str)
        except ValueError:
            actor_type = ActorType.PATIENT

        set_audit_context(actor_id, actor_type, request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ============================================================
# FastAPI 依赖注入
# ============================================================

async def get_audit_logger(
    session: AsyncSession = Depends(get_session),
) -> AuditLogger:
    """FastAPI Depends 注入 AuditLogger，与请求 session 共享事务"""
    return AuditLogger(session)
