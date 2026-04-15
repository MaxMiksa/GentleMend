"""
浅愈(GentleMend) — 事件接收与存储

POST /api/v1/events 接口实现:
  - 批量事件校验（枚举类型、必填字段）
  - 异步写入（不阻塞主请求）
  - bulk insert 优化
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.models import EventLog, EventType

router = APIRouter(prefix="/api/v1", tags=["events"])


# ============================================================
# 请求/响应模型
# ============================================================

class EventItem(BaseModel):
    """单个事件"""
    event_type: EventType
    timestamp: datetime
    session_id: str = Field(..., min_length=1, max_length=64)
    assessment_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    payload: dict[str, Any] | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_not_future(cls, v: datetime) -> datetime:
        """客户端时间戳不能超过服务端当前时间 5 分钟"""
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if (v - now).total_seconds() > 300:
            raise ValueError("客户端时间戳不能超过服务端时间5分钟")
        return v


class BatchEventRequest(BaseModel):
    """批量事件上报请求"""
    events: list[EventItem] = Field(..., min_length=1, max_length=50)


class BatchEventResponse(BaseModel):
    """批量事件上报响应"""
    accepted: int
    event_ids: list[uuid.UUID]


# ============================================================
# 异步批量写入
# ============================================================

async def _bulk_insert_events(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> None:
    """后台任务：批量 INSERT 事件到 event_logs 表"""
    try:
        await session.execute(insert(EventLog), rows)
        await session.commit()
    except Exception:
        await session.rollback()
        # 生产环境应接入 structlog 记录失败
        raise


# ============================================================
# 路由
# ============================================================

@router.post(
    "/events",
    response_model=BatchEventResponse,
    summary="批量上报前端事件",
    description="接收前端 EventTracker SDK 上报的可观测性事件，异步写入数据库。",
)
async def receive_events(
    body: BatchEventRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> BatchEventResponse:
    """
    接收并异步存储前端事件。

    流程:
      1. 校验事件列表（Pydantic 自动完成枚举、必填字段校验）
      2. 为每个事件生成 server 端 UUID 和 server_timestamp
      3. 提取客户端 IP 和 User-Agent
      4. 通过 BackgroundTasks 异步 bulk insert，不阻塞响应
    """
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    now = datetime.now(timezone.utc)

    event_ids: list[uuid.UUID] = []
    rows: list[dict[str, Any]] = []

    for evt in body.events:
        eid = uuid.uuid4()
        event_ids.append(eid)
        rows.append({
            "id": eid,
            "event_type": evt.event_type,
            "session_id": evt.session_id,
            "assessment_id": evt.assessment_id,
            "patient_id": evt.patient_id,
            "payload": evt.payload,
            "client_timestamp": evt.timestamp,
            "server_timestamp": now,
            "ip_address": ip,
            "user_agent": ua,
        })

    # 异步写入，不阻塞 HTTP 响应
    background_tasks.add_task(_bulk_insert_events, session, rows)

    return BatchEventResponse(accepted=len(rows), event_ids=event_ids)
