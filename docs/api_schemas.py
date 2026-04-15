"""
浅愈(GentleMend) — API Pydantic 模型定义
完整的请求/响应模型，可直接用于 FastAPI 路由。

技术栈: Python 3.11+ / Pydantic v2 / FastAPI
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, ConfigDict


# ============================================================
# 枚举定义
# ============================================================

class RiskLevel(str, Enum):
    """三级风险分层，映射 CTCAE 分级"""
    LOW = "low"          # CTCAE 1-2 级
    MEDIUM = "medium"    # CTCAE 3 级
    HIGH = "high"        # CTCAE 4-5 级


class SymptomCategory(str, Enum):
    """症状大类（基于乳腺癌常见副作用分类）"""
    GASTROINTESTINAL = "gastrointestinal"   # 消化系统
    DERMATOLOGICAL = "dermatological"       # 皮肤
    NEUROLOGICAL = "neurological"           # 神经系统
    HEMATOLOGICAL = "hematological"         # 血液系统
    CARDIOVASCULAR = "cardiovascular"       # 心血管
    MUSCULOSKELETAL = "musculoskeletal"     # 肌肉骨骼
    RESPIRATORY = "respiratory"             # 呼吸系统
    CONSTITUTIONAL = "constitutional"       # 全身症状（疲劳、发热等）
    ENDOCRINE = "endocrine"                 # 内分泌
    OTHER = "other"


class SeverityLevel(int, Enum):
    """症状严重程度（1-5，对应 CTCAE 分级）"""
    GRADE_1 = 1  # 轻度
    GRADE_2 = 2  # 中度
    GRADE_3 = 3  # 重度
    GRADE_4 = 4  # 危及生命
    GRADE_5 = 5  # 死亡相关


class ContactRequestStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class EventType(str, Enum):
    """PRD 定义的 5 个可观测性事件"""
    ASSESSMENT_STARTED = "assessment_started"
    ASSESSMENT_SUBMITTED = "assessment_submitted"
    RESULT_VIEWED = "result_viewed"
    CONTACT_TEAM_CLICKED = "contact_team_clicked"
    ASSESSMENT_CLOSED = "assessment_closed"


class ErrorCode(str, Enum):
    """业务错误码"""
    # 通用
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 评估业务
    ASSESSMENT_TIMEOUT = "ASSESSMENT_TIMEOUT"
    RULE_ENGINE_ERROR = "RULE_ENGINE_ERROR"
    AI_SERVICE_UNAVAILABLE = "AI_SERVICE_UNAVAILABLE"
    AI_DEGRADED = "AI_DEGRADED"              # AI 降级，仅返回规则引擎结果
    INPUT_TOO_SHORT = "INPUT_TOO_SHORT"
    INPUT_POTENTIALLY_HARMFUL = "INPUT_POTENTIALLY_HARMFUL"


# ============================================================
# 嵌套 / 共享模型
# ============================================================

class SymptomItem(BaseModel):
    """单个症状条目（结构化输入）"""
    category: SymptomCategory
    name: str = Field(..., min_length=1, max_length=100, examples=["恶心"])
    severity: SeverityLevel | None = Field(None, description="患者自评严重程度 1-5")
    frequency: str | None = Field(None, max_length=50, examples=["每天3-4次"])
    duration: str | None = Field(None, max_length=50, examples=["持续3天"])
    notes: str | None = Field(None, max_length=500, description="补充说明")


class Evidence(BaseModel):
    """评估依据 — 命中的规则或 AI 推理依据"""
    rule_id: str = Field(..., examples=["RULE-GI-001"])
    rule_version: str = Field(..., examples=["1.0.0"])
    rule_name: str = Field(..., examples=["化疗期间持续呕吐"])
    description: str = Field(..., description="规则命中原因的可读说明")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")
    source: str = Field(
        ...,
        description="依据来源: rule_engine / ai_enhanced",
        examples=["rule_engine"],
    )


class Advice(BaseModel):
    """单条处置建议"""
    action: str = Field(..., description="建议的具体行动")
    urgency: RiskLevel = Field(..., description="紧急程度")
    rationale: str = Field(..., description="建议理由（关联规则/指南）")
    reference: str | None = Field(None, description="临床指南引用，如 CTCAE v5.0")


class AuditMeta(BaseModel):
    """审计元数据 — 每次评估结果必须携带"""
    matched_rule_ids: list[str] = Field(..., description="命中规则 ID 列表")
    rule_versions: dict[str, str] = Field(
        ..., description="规则ID → 版本号映射",
    )
    engine_version: str = Field(..., examples=["0.1.0"])
    generated_at: datetime = Field(
        ..., description="结果生成时间（精确到毫秒）",
    )
    ai_model_version: str | None = Field(None, examples=["claude-sonnet-4-20250514"])
    ai_prompt_version: str | None = Field(None, examples=["1.2.0"])
    ai_raw_output: str | None = Field(
        None, description="AI 原始输出（审计用，不对外暴露）",
    )


# ============================================================
# 请求模型
# ============================================================

class AssessmentRequest(BaseModel):
    """POST /api/v1/assessments — 提交副作用评估"""
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(
        ...,
        min_length=2,
        max_length=5000,
        description="患者自然语言副作用描述",
        examples=["最近三天一直恶心，吃不下东西，今天吐了两次"],
    )
    symptoms: list[SymptomItem] | None = Field(
        None,
        description="可选的结构化症状列表（前端辅助输入）",
        max_length=20,
    )
    session_id: str | None = Field(
        None,
        description="前端会话 ID，用于关联事件链",
    )

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("描述内容不能为空白")
        return v


class ContactRequestCreate(BaseModel):
    """POST /api/v1/contact-requests — 创建协同请求"""
    assessment_id: uuid.UUID = Field(..., description="关联的评估 ID")
    message: str | None = Field(
        None, max_length=1000, description="患者附言",
    )
    urgency: RiskLevel = Field(
        default=RiskLevel.MEDIUM, description="紧急程度",
    )


class EventReport(BaseModel):
    """POST /api/v1/events — 前端事件上报"""
    event_type: EventType
    timestamp: datetime
    session_id: str = Field(..., max_length=64)
    assessment_id: uuid.UUID | None = None
    payload: dict[str, Any] | None = Field(
        None,
        description="事件附加数据",
        examples=[{"input_length": 120, "risk_level": "high", "duration": 35}],
    )


# ============================================================
# 响应模型
# ============================================================

class AssessmentResponse(BaseModel):
    """GET /api/v1/assessments/:id — 单次评估结果"""
    id: uuid.UUID
    risk_level: RiskLevel
    summary: str = Field(..., description="风险评估摘要（患者可读）")
    should_contact_team: bool = Field(
        ..., description="是否建议联系医疗团队",
    )
    evidences: list[Evidence] = Field(..., description="评估依据列表")
    advices: list[Advice] = Field(..., description="处置建议列表")
    disclaimer: str = Field(
        default="本评估结果仅供参考，不构成医疗诊断。如有紧急情况请立即就医。",
        description="医疗免责声明",
    )
    # 输入回显
    original_description: str
    symptoms: list[SymptomItem] | None = None
    # 审计
    audit: AuditMeta
    # 时间
    created_at: datetime
    version: int = Field(default=1, description="评估版本（不可变，追加新版本）")

    # AI 增强标记
    ai_enhanced: bool = Field(
        default=False, description="是否经过 AI 增强",
    )
    ai_degraded: bool = Field(
        default=False,
        description="AI 是否降级（True 表示仅规则引擎结果）",
    )


class AssessmentListItem(BaseModel):
    """列表页中的评估摘要条目"""
    id: uuid.UUID
    risk_level: RiskLevel
    summary: str
    should_contact_team: bool
    created_at: datetime
    symptom_count: int = Field(..., description="症状条目数")
    ai_enhanced: bool


class PaginationMeta(BaseModel):
    """分页元数据"""
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total_pages: int = Field(..., ge=0)


class AssessmentListResponse(BaseModel):
    """GET /api/v1/assessments — 历史评估列表（分页）"""
    items: list[AssessmentListItem]
    pagination: PaginationMeta


class ContactRequestResponse(BaseModel):
    """POST /api/v1/contact-requests 响应"""
    id: uuid.UUID
    assessment_id: uuid.UUID
    status: ContactRequestStatus
    urgency: RiskLevel
    message: str | None = None
    created_at: datetime


class EventReportResponse(BaseModel):
    """POST /api/v1/events 响应"""
    accepted: bool = True
    event_id: uuid.UUID


# ============================================================
# 错误响应
# ============================================================

class ErrorDetail(BaseModel):
    """单个字段级错误"""
    field: str | None = None
    message: str
    code: str | None = None


class ErrorResponse(BaseModel):
    """统一错误响应格式"""
    error: ErrorCode
    message: str
    details: list[ErrorDetail] | None = None
    request_id: str = Field(..., description="请求追踪 ID")
    timestamp: datetime


# ============================================================
# 健康检查
# ============================================================

class ComponentHealth(BaseModel):
    name: str
    status: str = Field(..., description="healthy / degraded / unhealthy")
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    """GET /api/v1/health"""
    status: str = Field(..., description="healthy / degraded / unhealthy")
    version: str
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    """GET /api/v1/health/ready — 含依赖服务连通性"""
    status: str
    components: list[ComponentHealth]


# ============================================================
# 查询参数模型（用于 FastAPI Depends）
# ============================================================

class AssessmentListParams(BaseModel):
    """GET /api/v1/assessments 查询参数"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    risk_level: RiskLevel | None = Field(None, description="按风险等级筛选")
    sort_by: str = Field(
        default="created_at",
        description="排序字段: created_at / risk_level",
    )
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    date_from: datetime | None = Field(None, description="起始时间")
    date_to: datetime | None = Field(None, description="截止时间")
