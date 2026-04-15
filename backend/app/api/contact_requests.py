"""
浅愈(GentleMend) — 协同请求 API
POST /contact-requests  创建协同请求
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.models import (
    Assessment, ContactRequest, ContactStatus, RiskLevel,
    AuditLog, ActorType,
)

router = APIRouter(prefix="/contact-requests", tags=["contact-requests"])


class ContactRequestCreate(BaseModel):
    assessment_id: str = Field(..., description="关联的评估ID")
    message: str | None = Field(None, description="患者留言")


class ContactRequestResponse(BaseModel):
    id: str
    assessment_id: str
    patient_id: str
    urgency: str
    message: str | None
    status: str

    model_config = {"from_attributes": True}


@router.post("/", response_model=ContactRequestResponse, status_code=201)
async def create_contact_request(
    req: ContactRequestCreate,
    session: AsyncSession = Depends(get_session),
):
    """创建协同请求：患者请求联系医疗团队"""
    assessment = await session.get(Assessment, req.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="评估记录不存在")

    urgency = assessment.risk_level or RiskLevel.LOW

    contact = ContactRequest(
        assessment_id=assessment.id,
        patient_id=assessment.patient_id,
        urgency=urgency,
        message=req.message,
        status=ContactStatus.PENDING,
    )
    session.add(contact)

    session.add(AuditLog(
        event_type="contact_request_created",
        entity_type="contact_request",
        entity_id=str(contact.id),
        actor_id=str(assessment.patient_id),
        actor_type=ActorType.PATIENT,
        new_value={
            "assessment_id": str(assessment.id),
            "urgency": urgency.value if isinstance(urgency, RiskLevel) else urgency,
        },
    ))

    await session.commit()
    await session.refresh(contact)

    return ContactRequestResponse(
        id=str(contact.id),
        assessment_id=str(contact.assessment_id),
        patient_id=str(contact.patient_id),
        urgency=contact.urgency.value,
        message=contact.message,
        status=contact.status.value,
    )
