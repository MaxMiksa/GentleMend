"""
浅愈(GentleMend) — 审计链完整性校验

功能:
  - BIGSERIAL 连续性校验（检测 gap）
  - HMAC-SHA256 签名批量验证
  - 定期完整性校验任务
  - 防篡改报告生成
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuditLog
from app.observability.audit import verify_signature


@dataclass
class IntegrityReport:
    """完整性校验报告"""
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    total_records: int = 0
    id_gaps: list[tuple[int, int]] = field(default_factory=list)
    signature_failures: list[int] = field(default_factory=list)
    is_healthy: bool = True
    details: str = ""


# ============================================================
# BIGSERIAL 连续性校验
# ============================================================

async def check_id_continuity(
    session: AsyncSession,
    start_id: int = 1,
    end_id: int | None = None,
) -> list[tuple[int, int]]:
    """
    检测 audit_logs.id (BIGSERIAL) 是否存在 gap。

    使用窗口函数 lead() 高效检测，避免全表扫描。
    返回 gap 列表: [(gap_start, gap_end), ...]
    """
    if end_id is None:
        result = await session.execute(
            select(func.max(AuditLog.id)),
        )
        end_id = result.scalar() or 0

    if end_id == 0:
        return []

    # 使用 lead() 窗口函数检测不连续的 id
    gap_query = text("""
        WITH id_gaps AS (
            SELECT
                id,
                lead(id) OVER (ORDER BY id) AS next_id
            FROM audit_logs
            WHERE id BETWEEN :start_id AND :end_id
        )
        SELECT id + 1 AS gap_start, next_id - 1 AS gap_end
        FROM id_gaps
        WHERE next_id - id > 1
        ORDER BY id
        LIMIT 1000
    """)

    result = await session.execute(
        gap_query, {"start_id": start_id, "end_id": end_id},
    )
    return [(row[0], row[1]) for row in result.fetchall()]


# ============================================================
# HMAC 签名批量验证
# ============================================================

async def verify_signatures_batch(
    session: AsyncSession,
    batch_size: int = 500,
    start_id: int = 1,
    end_id: int | None = None,
) -> list[int]:
    """
    批量验证审计记录的 HMAC 签名。
    返回签名不匹配的记录 id 列表。
    """
    failures: list[int] = []

    if end_id is None:
        result = await session.execute(
            select(func.max(AuditLog.id)),
        )
        end_id = result.scalar() or 0

    current = start_id
    while current <= end_id:
        batch_end = min(current + batch_size, end_id)
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.id.between(current, batch_end),
            ).order_by(AuditLog.id),
        )
        rows = result.scalars().all()

        for row in rows:
            meta = row.metadata_ or {}
            stored_sig = meta.get("hmac_sha256", "")
            if not stored_sig:
                failures.append(row.id)
                continue

            record_dict = {
                "id": "pending",  # 签名时 id 尚未分配
                "event_type": row.event_type,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "created_at": str(row.created_at),
            }
            if not verify_signature(record_dict, stored_sig):
                failures.append(row.id)

        current = batch_end + 1

    return failures


# ============================================================
# 综合完整性校验
# ============================================================

async def run_integrity_check(
    session: AsyncSession,
) -> IntegrityReport:
    """
    执行完整的审计链完整性校验。

    检查项:
      1. BIGSERIAL 连续性（是否有被删除的记录）
      2. HMAC 签名验证（是否有被篡改的记录）
    """
    report = IntegrityReport()

    # 总记录数
    result = await session.execute(
        select(func.count(AuditLog.id)),
    )
    report.total_records = result.scalar() or 0

    if report.total_records == 0:
        report.details = "审计表为空，无需校验"
        return report

    # 1. ID 连续性
    report.id_gaps = await check_id_continuity(session)

    # 2. 签名验证
    report.signature_failures = await verify_signatures_batch(session)

    # 判定健康状态
    if report.id_gaps or report.signature_failures:
        report.is_healthy = False
        parts = []
        if report.id_gaps:
            parts.append(f"发现 {len(report.id_gaps)} 个 ID gap")
        if report.signature_failures:
            parts.append(
                f"发现 {len(report.signature_failures)} 条签名异常记录"
            )
        report.details = "；".join(parts)
    else:
        report.details = (
            f"校验通过：{report.total_records} 条记录，"
            "ID 连续，签名完整"
        )

    return report
