"""
浅愈(GentleMend) — 患者管理 API (MVP)
POST /patients     创建患者
GET  /patients/:id 获取患者信息
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.models.models import Patient, Gender

router = APIRouter(prefix="/patients", tags=["patients"])


class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="姓名")
    age: int = Field(..., ge=0, le=150, description="年龄")
    gender: str = Field(..., description="性别: male/female/other")
    diagnosis: str | None = Field(None, max_length=500, description="诊断")
    treatment_regimen: str | None = Field(None, max_length=500, description="治疗方案")


class PatientResponse(BaseModel):
    id: str
    name: str
    age: int
    gender: str
    diagnosis: str | None = None
    treatment_regimen: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/", response_model=PatientResponse, status_code=201)
async def create_patient(
    req: PatientCreate,
    session: AsyncSession = Depends(get_session),
):
    """创建患者"""
    patient = Patient(
        name=req.name,
        age=req.age,
        gender=Gender(req.gender),
        diagnosis=req.diagnosis,
        treatment_regimen=req.treatment_regimen,
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    return PatientResponse(
        id=str(patient.id),
        name=patient.name,
        age=patient.age,
        gender=patient.gender.value,
        diagnosis=patient.diagnosis,
        treatment_regimen=patient.treatment_regimen,
        created_at=patient.created_at,
    )


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取患者信息"""
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="患者不存在")

    return PatientResponse(
        id=str(patient.id),
        name=patient.name,
        age=patient.age,
        gender=patient.gender.value,
        diagnosis=patient.diagnosis,
        treatment_regimen=patient.treatment_regimen,
        created_at=patient.created_at,
    )
