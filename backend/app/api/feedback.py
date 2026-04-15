"""
浅愈(GentleMend) — 患者反馈 API
POST /assessments/{id}/feedback  提交反馈（幂等，每次评估只允许一条）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.models import Assessment, PatientFeedback

router = APIRouter(prefix="/assessments", tags=["feedback"])


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="满意度 1-5")
    is_helpful: bool = Field(..., description="评估结果是否有帮助")
    comment: str | None = Field(None, max_length=500, description="文字反馈")


class FeedbackResponse(BaseModel):
    id: str
    assessment_id: str
    rating: int
    is_helpful: bool
    comment: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/{assessment_id}/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    assessment_id: str,
    req: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
):
    """提交患者反馈，每次评估只允许一条（幂等）"""
    assessment = await session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="评估不存在")

    existing = await session.execute(
        select(PatientFeedback).where(PatientFeedback.assessment_id == assessment_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该评估已有反馈记录")

    feedback = PatientFeedback(
        assessment_id=assessment_id,
        rating=req.rating,
        is_helpful=req.is_helpful,
        comment=req.comment,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)

    return FeedbackResponse(
        id=str(feedback.id),
        assessment_id=str(feedback.assessment_id),
        rating=feedback.rating,
        is_helpful=feedback.is_helpful,
        comment=feedback.comment,
        created_at=str(feedback.created_at),
    )
