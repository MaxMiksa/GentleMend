"""
执行层数据模型 — Pydantic v2

核心模型:
  - AdviceItem / AdviceBundle: 建议生成结果
  - CollaborationRequest: 协同请求
  - NotificationChannel: 通知渠道
  - AssessmentSnapshot: 不可变评估快照
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================

class AdviceUrgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class AdviceSource(str, Enum):
    RULE_ENGINE = "rule_engine"
    AI_ENHANCED = "ai_enhanced"
    HYBRID = "hybrid"

class NotificationChannel(str, Enum):
    APP_PUSH = "app_push"
    SMS = "sms"
    PHONE_CALL = "phone_call"

class CollaborationStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"

class EscalationLevel(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"       # 24h 未响应
    CRITICAL = "critical"       # 48h 未响应


# ============================================================
# 建议模型
# ============================================================

# 免责声明
DISCLAIMER_ZH = (
    "本评估结果仅供参考，不构成医疗诊断或治疗建议。"
    "如有紧急情况请立即拨打120或前往最近的急诊科。"
    "请遵循您的主治医生的专业指导。"
)


class AdviceItem(BaseModel):
    """单条处置建议"""
    advice_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())[:8],
    )
    action: str = Field(..., description="建议的具体行动")
    urgency: AdviceUrgency
    rationale: str = Field(..., description="建议理由")
    reference: str | None = Field(None, description="临床指南引用")
    source: AdviceSource = Field(default=AdviceSource.RULE_ENGINE)
    priority: int = Field(default=0, description="排序优先级，越大越靠前")
    # 双版本内容
    patient_text: str = Field(..., description="患者版（通俗易懂）")
    clinician_text: str = Field(default="", description="医生版（专业详细）")


class AdviceBundle(BaseModel):
    """建议包 — 一次评估的所有建议"""
    advices: list[AdviceItem] = Field(default_factory=list)
    summary_patient: str = Field(default="", description="患者版摘要")
    summary_clinician: str = Field(default="", description="医生版摘要")
    disclaimer: str = Field(default=DISCLAIMER_ZH)
    ai_enhanced: bool = Field(default=False)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# 协同请求
# ============================================================

class NotificationTarget(BaseModel):
    """通知目标"""
    channels: list[NotificationChannel]
    reason: str
    priority: str  # "urgent" / "high" / "normal"


class CollaborationRequest(BaseModel):
    """协同请求"""
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
    )
    assessment_id: str
    patient_id: str
    trigger_type: str = Field(
        ..., description="auto / manual",
    )
    trigger_event: str = Field(
        default="", description="触发事件名称",
    )
    urgency: AdviceUrgency
    notification: NotificationTarget
    message_patient: str = Field(default="")
    message_clinician: str = Field(default="")
    status: CollaborationStatus = Field(
        default=CollaborationStatus.PENDING,
    )
    escalation_level: EscalationLevel = Field(
        default=EscalationLevel.NORMAL,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None


# ============================================================
# 不可变快照
# ============================================================

class AssessmentSnapshot(BaseModel):
    """
    Assessment 聚合根的不可变快照。
    一旦生成不可修改，只能追加新版本。
    """
    snapshot_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
    )
    assessment_id: str
    version: int = Field(default=1, ge=1)
    # 输入
    original_description: str
    symptoms_structured: list[dict[str, Any]] = Field(default_factory=list)
    # 决策结果
    risk_level: str
    urgency: str
    should_contact_team: bool
    ctcae_grades: dict[str, int]
    overall_risk_score: float
    normalized_risk_score: float
    # 建议
    advices: list[dict[str, Any]] = Field(default_factory=list)
    # 依据
    evidences: list[dict[str, Any]] = Field(default_factory=list)
    # 审计
    matched_rule_ids: list[str]
    rule_versions: dict[str, str]
    engine_version: str
    audit_trail_id: str
    confidence: float
    # AI 标记
    ai_enhanced: bool = False
    ai_degraded: bool = False
    ai_model_version: str | None = None
    ai_prompt_version: str | None = None
    # 免责声明
    disclaimer: str = DISCLAIMER_ZH
    # 时间与完整性
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    content_hash: str = Field(
        default="", description="快照内容的 SHA-256 hash",
    )

    def compute_hash(self) -> str:
        """计算快照内容 hash，用于完整性校验"""
        # 排除 content_hash 和 snapshot_id 本身
        data = self.model_dump(exclude={"content_hash", "snapshot_id"})
        # datetime 序列化
        raw = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def freeze(self) -> AssessmentSnapshot:
        """冻结快照：计算 hash 并返回不可变副本"""
        h = self.compute_hash()
        return self.model_copy(update={"content_hash": h})
