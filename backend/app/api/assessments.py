"""
浅愈(GentleMend) — 评估 API
POST /assessments  提交评估
GET  /assessments  历史列表
GET  /assessments/:id  单次结果
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import get_session
from app.models.models import (
    Assessment, AssessmentStatus, RiskLevel,
    Advice, AdviceSourceType, Evidence,
    Patient, AuditLog, ActorType,
)
from app.rules.engine import RuleEngine, get_rule_engine

router = APIRouter(prefix="/assessments", tags=["assessments"])


# ── Pydantic Schemas ──

class SymptomInput(BaseModel):
    name: str = Field(..., description="症状名称")
    severity: int = Field(1, ge=1, le=10, description="严重程度 1-10")
    frequency: str | None = Field(None, description="频率")
    body_region: str | None = Field(None, description="身体部位")


class AssessmentRequest(BaseModel):
    patient_id: str = Field(..., description="患者ID")
    symptoms: list[SymptomInput] = Field(default_factory=list)
    free_text: str = Field("", description="自由文本描述")
    medication_info: str = Field("", description="用药与手术信息")
    medical_history: str = Field("", description="既往病史")


class EvidenceResponse(BaseModel):
    rule_id: str
    rule_version: str
    confidence: float
    evidence_text: str | None = None

    model_config = {"from_attributes": True}


class AdviceResponse(BaseModel):
    content: str
    advice_type: str
    priority: int
    source_type: str

    model_config = {"from_attributes": True}


class AssessmentResponse(BaseModel):
    id: str
    patient_id: str
    status: str
    risk_level: str | None = None
    overall_risk_score: float | None = None
    free_text_input: str
    symptoms_structured: list | dict | None = None
    ctcae_grades: dict | None = None
    advices: list[AdviceResponse] = []
    evidences: list[EvidenceResponse] = []
    patient_explanation: str | None = None
    grading_rationale: str | None = None
    rule_engine_version: str | None = None
    ai_extraction_used: bool = False
    ai_enhancement_used: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AssessmentListItem(BaseModel):
    id: str
    risk_level: str | None = None
    status: str
    free_text_input: str
    symptom_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    items: list[AssessmentListItem]
    total: int
    page: int
    page_size: int


# ── Routes ──

@router.post("/", response_model=AssessmentResponse, status_code=201)
async def submit_assessment(
    req: AssessmentRequest,
    session: AsyncSession = Depends(get_session),
    rule_engine: RuleEngine = Depends(get_rule_engine),
):
    """提交副作用描述，触发评估"""
    patient_id = req.patient_id

    # 1. 验证患者存在
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="患者不存在")

    # 2. 构建症状数据
    symptoms_data = [s.model_dump() for s in req.symptoms]

    # 3. 规则引擎评估
    grading_result = rule_engine.evaluate(symptoms_data, req.free_text)
    ai_meta = grading_result.get("ai_meta")

    # 3.5 AI增强 — 生成个性化解释和建议
    ai_enhancement_used = False
    patient_explanation = grading_result["patient_explanation"]
    enhanced_advice_text = ""
    ai_raw_outputs = {"extraction": ai_meta["raw_output"]} if ai_meta else {}

    from app.ai.extractor import enhance_with_ai
    enhancement = enhance_with_ai(
        free_text=req.free_text,
        risk_level=grading_result["risk_level"],
        ctcae_grades=grading_result["ctcae_grades"],
        advices=grading_result["advices"],
        medication_info=req.medication_info,
        medical_history=req.medical_history,
        symptom_details=grading_result.get("symptom_details"),
    )
    if enhancement:
        ai_enhancement_used = True
        patient_explanation = enhancement["explanation"]
        enhanced_advice_text = enhancement["personalized_advice"]
        ai_raw_outputs["enhancement"] = enhancement["raw_output"]

    # 4. 创建Assessment（不可变）
    assessment_id = str(uuid.uuid4())
    assessment = Assessment(
        id=assessment_id,
        patient_id=patient_id,
        status=AssessmentStatus.COMPLETED,
        risk_level=RiskLevel(grading_result["risk_level"]),
        free_text_input=req.free_text or "",
        symptoms_structured=symptoms_data,
        ctcae_grades=grading_result["ctcae_grades"],
        overall_risk_score=grading_result["risk_score"],
        rule_engine_version=rule_engine.version,
        grading_rationale=grading_result["rationale"],
        patient_explanation=patient_explanation,
        ai_extraction_used=grading_result.get("ai_extraction_used", False),
        ai_enhancement_used=ai_enhancement_used,
        ai_model_version=enhancement["model"] if enhancement else (ai_meta["model"] if ai_meta else None),
        prompt_version=ai_meta["prompt_version"] if ai_meta else None,
        ai_raw_output=ai_raw_outputs or None,
    )
    session.add(assessment)

    # 5. 创建Advice记录
    for adv in grading_result["advices"]:
        session.add(Advice(
            assessment_id=assessment.id,
            content=adv["content"],
            advice_type=adv["type"],
            priority=adv["priority"],
            source_type=AdviceSourceType.RULE,
        ))

    # 5.5 AI增强建议（如果有）
    if enhanced_advice_text:
        session.add(Advice(
            assessment_id=assessment.id,
            content=enhanced_advice_text,
            advice_type="ai_personalized",
            priority=5,
            source_type=AdviceSourceType.AI,
        ))

    # 6. 创建Evidence记录
    for ev in grading_result["evidences"]:
        session.add(Evidence(
            assessment_id=assessment.id,
            rule_id=ev["rule_id"],
            rule_version=ev["rule_version"],
            confidence=ev["confidence"],
            matched_conditions=ev.get("matched_conditions"),
            evidence_text=ev["evidence_text"],
        ))

    # 7. 审计日志
    session.add(AuditLog(
        event_type="assessment_created",
        entity_type="assessment",
        entity_id=str(assessment.id),
        actor_id=str(patient_id),
        actor_type=ActorType.PATIENT,
        new_value={
            "risk_level": grading_result["risk_level"],
            "rule_engine_version": rule_engine.version,
            "symptom_count": len(symptoms_data),
        },
    ))

    await session.commit()
    await session.refresh(assessment)

    # 加载关联数据
    result = await session.execute(
        select(Assessment)
        .options(selectinload(Assessment.advices), selectinload(Assessment.evidences))
        .where(Assessment.id == assessment.id)
    )
    assessment = result.scalar_one()

    return _to_response(assessment)


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    assessment_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取单次评估结果"""
    result = await session.execute(
        select(Assessment)
        .options(selectinload(Assessment.advices), selectinload(Assessment.evidences))
        .where(Assessment.id == assessment_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    return _to_response(assessment)


@router.get("/", response_model=PaginatedResponse)
async def list_assessments(
    patient_id: str | None = Query(None, description="按患者ID筛选"),
    risk_level: str | None = Query(None, description="按风险等级筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """获取历史评估列表"""
    query = select(Assessment).order_by(desc(Assessment.created_at))
    count_query = select(func.count(Assessment.id))

    if patient_id:
        pid = patient_id
        query = query.where(Assessment.patient_id == pid)
        count_query = count_query.where(Assessment.patient_id == pid)
    if risk_level:
        query = query.where(Assessment.risk_level == RiskLevel(risk_level))
        count_query = count_query.where(Assessment.risk_level == RiskLevel(risk_level))

    total = (await session.execute(count_query)).scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    assessments = result.scalars().all()

    items = []
    for a in assessments:
        symptom_count = len(a.symptoms_structured) if a.symptoms_structured else 0
        items.append(AssessmentListItem(
            id=str(a.id),
            risk_level=a.risk_level.value if a.risk_level else None,
            status=a.status.value,
            free_text_input=a.free_text_input,
            symptom_count=symptom_count,
            created_at=a.created_at,
        ))

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


def _to_response(a: Assessment) -> AssessmentResponse:
    return AssessmentResponse(
        id=str(a.id),
        patient_id=str(a.patient_id),
        status=a.status.value,
        risk_level=a.risk_level.value if a.risk_level else None,
        overall_risk_score=a.overall_risk_score,
        free_text_input=a.free_text_input,
        symptoms_structured=a.symptoms_structured,
        ctcae_grades=a.ctcae_grades,
        advices=[AdviceResponse(
            content=adv.content,
            advice_type=adv.advice_type,
            priority=adv.priority,
            source_type=adv.source_type.value,
        ) for adv in a.advices],
        evidences=[EvidenceResponse(
            rule_id=ev.rule_id,
            rule_version=ev.rule_version,
            confidence=ev.confidence,
            evidence_text=ev.evidence_text,
        ) for ev in a.evidences],
        patient_explanation=a.patient_explanation,
        grading_rationale=a.grading_rationale,
        rule_engine_version=a.rule_engine_version,
        ai_extraction_used=a.ai_extraction_used,
        ai_enhancement_used=a.ai_enhancement_used,
        created_at=a.created_at,
    )
