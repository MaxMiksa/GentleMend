"""
浅愈(GentleMend) — 事件上报 API
POST /events  批量事件上报
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session, async_session
from app.models.models import EventLog, EventType

router = APIRouter(prefix="/events", tags=["events"])

# 允许的事件类型
ALLOWED_EVENT_TYPES = {e.value for e in EventType}


class EventInput(BaseModel):
    event_type: str = Field(..., description="事件类型")
    session_id: str = Field(..., description="会话ID")
    assessment_id: str | None = Field(None, description="评估ID")
    patient_id: str | None = Field(None, description="患者ID")
    payload: dict | None = Field(None, description="事件载荷")
    timestamp: datetime | None = Field(None, description="客户端时间戳(前端字段名)")
    client_timestamp: datetime | None = Field(None, description="客户端时间戳")

    @property
    def resolved_timestamp(self) -> datetime:
        return self.client_timestamp or self.timestamp or datetime.utcnow()


class EventBatchRequest(BaseModel):
    events: list[EventInput] = Field(..., min_length=1)


class EventBatchResponse(BaseModel):
    accepted: int
    message: str = "events accepted"


async def _persist_events(events: list[EventInput]) -> None:
    """异步写入事件到数据库"""
    async with async_session() as session:
        for ev in events:
            log = EventLog(
                event_type=EventType(ev.event_type),
                session_id=ev.session_id,
                assessment_id=ev.assessment_id if ev.assessment_id else None,
                patient_id=ev.patient_id if ev.patient_id else None,
                payload=ev.payload,
                client_timestamp=ev.resolved_timestamp,
            )
            session.add(log)
        await session.commit()


@router.post("/", response_model=EventBatchResponse, status_code=202)
async def batch_events(
    req: EventBatchRequest,
    background_tasks: BackgroundTasks,
):
    """批量事件上报，异步写入"""
    # 校验 event_type 枚举
    for ev in req.events:
        if ev.event_type not in ALLOWED_EVENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效的事件类型: {ev.event_type}，"
                       f"允许的类型: {', '.join(sorted(ALLOWED_EVENT_TYPES))}",
            )

    background_tasks.add_task(_persist_events, req.events)

    return EventBatchResponse(accepted=len(req.events))
