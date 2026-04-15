"""
浅愈(GentleMend) — SQLAlchemy 2.0 ORM 模型定义
所有 9 个核心实体: Patient, Assessment, Advice, Evidence,
RuleSource, EventLog, AuditLog, ContactRequest, PromptRegistry

设计原则:
  - Assessment 不可变 (无 updated_at)
  - AuditLog append-only (数据库层 REVOKE UPDATE/DELETE)
  - JSONB 存储半结构化数据
  - 每条建议关联到具体规则来源
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, DATABASE_URL

# 类型适配：PostgreSQL 用原生类型，SQLite 用通用类型
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import String as UUID_TYPE
    JSONB = JSON
    INET = String

    def _uuid_col(**kwargs):
        return mapped_column(String(36), **kwargs)
else:
    from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
    UUID_TYPE = PG_UUID

    def _uuid_col(**kwargs):
        return mapped_column(PG_UUID(as_uuid=True), **kwargs)


# ============================================================
# 枚举类型
# ============================================================

class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AssessmentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AdviceSourceType(str, enum.Enum):
    RULE = "rule"
    AI = "ai"
    HYBRID = "hybrid"


class RuleStatus(str, enum.Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DRAFT = "draft"


class EventType(str, enum.Enum):
    ASSESSMENT_STARTED = "assessment_started"
    ASSESSMENT_SUBMITTED = "assessment_submitted"
    RESULT_VIEWED = "result_viewed"
    CONTACT_TEAM_CLICKED = "contact_team_clicked"
    ASSESSMENT_CLOSED = "assessment_closed"


class ActorType(str, enum.Enum):
    PATIENT = "patient"
    CLINICIAN = "clinician"
    SYSTEM = "system"


class ContactStatus(str, enum.Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


# ============================================================
# 实体模型
# ============================================================

class Patient(Base):
    """患者表"""
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender_enum", create_constraint=True),
        nullable=False,
    )
    diagnosis: Mapped[str | None] = mapped_column(String(500))
    treatment_regimen: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    # -- relationships --
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="patient", lazy="selectin",
    )
    contact_requests: Mapped[list[ContactRequest]] = relationship(
        back_populates="patient", lazy="selectin",
    )
    event_logs: Mapped[list[EventLog]] = relationship(
        back_populates="patient", lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("age >= 0 AND age <= 150", name="ck_patients_age"),
        Index("ix_patients_created_at", "created_at"),
    )


class Assessment(Base):
    """
    评估表 — 核心实体，不可变
    创建后不可修改，只能追加新版本。无 updated_at 字段。
    """
    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus, name="assessment_status_enum"),
        nullable=False, default=AssessmentStatus.PENDING,
    )
    risk_level: Mapped[RiskLevel | None] = mapped_column(
        Enum(RiskLevel, name="risk_level_enum"),
    )
    free_text_input: Mapped[str] = mapped_column(Text, nullable=False)
    symptoms_structured: Mapped[dict | None] = mapped_column(JSONB)
    ctcae_grades: Mapped[dict | None] = mapped_column(JSONB)
    overall_risk_score: Mapped[float | None] = mapped_column(Float)

    # AI 相关字段
    ai_extraction_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    ai_enhancement_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    ai_model_version: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    ai_raw_output: Mapped[dict | None] = mapped_column(JSONB)

    # 规则引擎
    rule_engine_version: Mapped[str | None] = mapped_column(String(50))

    # 可读解释
    patient_explanation: Mapped[str | None] = mapped_column(Text)
    grading_rationale: Mapped[str | None] = mapped_column(Text)

    # 不可变: 只有 created_at，精确到毫秒
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # -- relationships --
    patient: Mapped[Patient] = relationship(back_populates="assessments")
    advices: Mapped[list[Advice]] = relationship(
        back_populates="assessment", lazy="selectin",
    )
    evidences: Mapped[list[Evidence]] = relationship(
        back_populates="assessment", lazy="selectin",
    )
    contact_requests: Mapped[list[ContactRequest]] = relationship(
        back_populates="assessment", lazy="selectin",
    )
    event_logs: Mapped[list[EventLog]] = relationship(
        back_populates="assessment", lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "overall_risk_score IS NULL OR "
            "(overall_risk_score >= 0 AND overall_risk_score <= 1)",
            name="ck_assessments_risk_score",
        ),
        Index("ix_assessments_patient_id", "patient_id"),
        Index("ix_assessments_status", "status"),
        Index("ix_assessments_risk_level", "risk_level"),
        Index("ix_assessments_created_at", "created_at"),
        Index(
            "ix_assessments_patient_created",
            "patient_id", "created_at",
        ),
    )


class Advice(Base):
    """建议表 — 每条建议关联一次评估"""
    __tablename__ = "advices"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    advice_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    source_type: Mapped[AdviceSourceType] = mapped_column(
        Enum(AdviceSourceType, name="advice_source_type_enum"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # -- relationships --
    assessment: Mapped[Assessment] = relationship(back_populates="advices")

    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_advices_priority"),
        Index("ix_advices_assessment_id", "assessment_id"),
        Index("ix_advices_source_type", "source_type"),
    )


class Evidence(Base):
    """依据表 — 评估命中的规则证据"""
    __tablename__ = "evidences"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="业务规则ID，如 RULE-NAUSEA-G3-001",
    )
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_conditions: Mapped[dict | None] = mapped_column(JSONB)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # -- relationships --
    assessment: Mapped[Assessment] = relationship(back_populates="evidences")

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_evidences_confidence",
        ),
        Index("ix_evidences_assessment_id", "assessment_id"),
        Index("ix_evidences_rule_id", "rule_id"),
    )


class RuleSource(Base):
    """规则来源表 — 版本化的规则定义"""
    __tablename__ = "rule_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    rule_id: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="业务规则ID，如 RULE-NAUSEA-G3-001",
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    ctcae_term: Mapped[str | None] = mapped_column(String(100))
    ctcae_grade: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[RuleStatus] = mapped_column(
        Enum(RuleStatus, name="rule_status_enum"),
        nullable=False, default=RuleStatus.DRAFT,
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    created_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    review_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="uq_rule_sources_rule_version"),
        CheckConstraint(
            "ctcae_grade IS NULL OR (ctcae_grade >= 1 AND ctcae_grade <= 5)",
            name="ck_rule_sources_ctcae_grade",
        ),
        CheckConstraint("priority >= 0", name="ck_rule_sources_priority"),
        Index("ix_rule_sources_rule_id", "rule_id"),
        Index("ix_rule_sources_status", "status"),
        Index("ix_rule_sources_category", "category"),
        Index("ix_rule_sources_ctcae_term", "ctcae_term"),
    )


class EventLog(Base):
    """事件日志表 — 可观测性事件"""
    __tablename__ = "event_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="event_type_enum"), nullable=False,
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="SET NULL"),
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="SET NULL"),
    )
    payload: Mapped[dict | None] = mapped_column(JSONB)
    client_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    server_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))

    # -- relationships --
    assessment: Mapped[Assessment | None] = relationship(
        back_populates="event_logs",
    )
    patient: Mapped[Patient | None] = relationship(
        back_populates="event_logs",
    )

    __table_args__ = (
        Index("ix_event_logs_event_type", "event_type"),
        Index("ix_event_logs_session_id", "session_id"),
        Index("ix_event_logs_assessment_id", "assessment_id"),
        Index("ix_event_logs_server_timestamp", "server_timestamp"),
        Index(
            "ix_event_logs_patient_timestamp",
            "patient_id", "server_timestamp",
        ),
    )


class AuditLog(Base):
    """
    审计日志表 — append-only
    数据库层 REVOKE UPDATE/DELETE，仅允许 INSERT 和 SELECT。
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        String(36), default=lambda: str(uuid.uuid4()), nullable=False, unique=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    actor_type: Mapped[ActorType | None] = mapped_column(
        Enum(ActorType, name="actor_type_enum"),
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, comment="额外元数据",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )


class ContactRequest(Base):
    """联系请求表 — 患者请求联系医疗团队"""
    __tablename__ = "contact_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
    )
    urgency: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level_enum", create_constraint=False),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContactStatus] = mapped_column(
        Enum(ContactStatus, name="contact_status_enum"),
        nullable=False, default=ContactStatus.PENDING,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # -- relationships --
    assessment: Mapped[Assessment] = relationship(
        back_populates="contact_requests",
    )
    patient: Mapped[Patient] = relationship(
        back_populates="contact_requests",
    )

    __table_args__ = (
        Index("ix_contact_requests_assessment_id", "assessment_id"),
        Index("ix_contact_requests_patient_id", "patient_id"),
        Index("ix_contact_requests_status", "status"),
    )


class PatientFeedback(Base):
    """患者反馈表 — 智能体闭环的学习入口"""
    __tablename__ = "patient_feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False, unique=True,  # 每次评估只允许一条反馈
    )
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False,  # 1-5 满意度
    )
    is_helpful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    assessment: Mapped[Assessment] = relationship(backref="feedback")


class PromptRegistry(Base):
    """Prompt 注册表 — 管理 AI prompt 版本"""
    __tablename__ = "prompt_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    prompt_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 hash",
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    activated_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "prompt_name", "version",
            name="uq_prompt_registry_name_version",
        ),
        Index("ix_prompt_registry_active", "prompt_name", "is_active"),
    )
