"""
决策层数据模型 — Pydantic v2

核心模型:
  - SymptomGrade: 单症状 CTCAE 分级结果
  - RiskScore: 多症状综合风险评分
  - ConflictResolution: 冲突解决结果
  - DecisionConfidence: 置信度计算结果
  - AuditTrail / AuditStep: 决策审计链
  - DecisionResult: 决策层最终输出
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class UrgencyLevel(str, Enum):
    SELF_MONITOR = "self_monitor"
    CONTACT_ROUTINE = "contact_team_routine"
    CONTACT_24H = "contact_team_24h"
    EMERGENCY = "emergency_immediate"

class MatchType(str, Enum):
    """规则匹配类型"""
    EXACT = "exact"            # 完全匹配
    PARTIAL = "partial"        # 部分条件匹配
    FUZZY = "fuzzy"            # 模糊匹配（关键词相似）
    DRUG_BOOSTED = "drug_boosted"  # 药物关联提升

class UrgencyFactor(str, Enum):
    """紧迫因子类型"""
    ACUTE_ONSET = "acute_onset"          # 急性发作
    PROGRESSIVE = "progressive"          # 进行性加重
    STABLE = "stable"                    # 稳定
    IMPROVING = "improving"             # 好转中

class RulePriority(str, Enum):
    """规则优先级分类"""
    SAFETY = "safety"          # 安全规则 >= 900
    GUIDELINE = "guideline"    # 指南规则 700-899
    CONSENSUS = "consensus"    # 专家共识 500-699
    EMPIRICAL = "empirical"    # 经验规则 < 500


# ============================================================
# 单症状分级
# ============================================================

class SymptomGrade(BaseModel):
    """单症状 CTCAE 分级结果"""
    symptom_type: str = Field(..., description="CTCAE标准术语")
    ctcae_grade: int = Field(..., ge=1, le=5, description="CTCAE等级 1-5")
    matched_rule_id: str = Field(..., description="命中的规则ID")
    match_type: MatchType = Field(default=MatchType.EXACT)
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    matched_conditions: dict[str, Any] = Field(
        default_factory=dict, description="命中的条件详情",
    )
    risk_level: RiskLevel = Field(..., description="该症状对应的风险等级")
    urgency: UrgencyLevel = Field(..., description="该症状的紧急度")
    patient_message: str = Field(..., description="患者端提示")
    clinician_message: str = Field(default="", description="医生端摘要")


# ============================================================
# 风险评分
# ============================================================

# 症状权重表：不同症状的基础权重（反映临床严重性差异）
SYMPTOM_WEIGHTS: dict[str, float] = {
    # 血液系统 — 权重最高（粒缺性发热可致命）
    "febrile_neutropenia": 5.0,
    "neutropenia": 4.0,
    "thrombocytopenia": 3.5,
    "anemia": 2.5,
    # 心血管 — 高权重
    "cardiac_toxicity": 4.5,
    "thromboembolism": 4.0,
    "chest_pain": 4.5,
    # 呼吸系统
    "dyspnea": 4.0,
    "pneumonitis": 3.5,
    # 过敏
    "anaphylaxis": 5.0,
    "allergic_reaction": 3.5,
    # 消化系统 — 中等权重
    "nausea": 1.5,
    "vomiting": 2.0,
    "diarrhea": 2.0,
    "mucositis": 2.0,
    # 神经系统
    "peripheral_neuropathy": 2.5,
    "consciousness_change": 5.0,
    # 皮肤
    "rash": 1.0,
    "hand_foot_syndrome": 1.5,
    # 全身/内分泌 — 较低权重
    "fatigue": 1.0,
    "arthralgia": 1.0,
    "hot_flash": 0.5,
    "alopecia": 0.3,
    # 出血
    "bleeding": 4.0,
}

# 紧迫因子映射
URGENCY_FACTOR_VALUES: dict[UrgencyFactor, float] = {
    UrgencyFactor.ACUTE_ONSET: 2.0,
    UrgencyFactor.PROGRESSIVE: 1.5,
    UrgencyFactor.STABLE: 1.0,
    UrgencyFactor.IMPROVING: 0.7,
}

# 症状交互效应表：特定症状组合的额外风险乘数
SYMPTOM_INTERACTIONS: dict[frozenset[str], float] = {
    frozenset({"nausea", "fever"}): 1.4,
    frozenset({"nausea", "vomiting"}): 1.3,
    frozenset({"diarrhea", "vomiting"}): 1.5,       # 脱水风险
    frozenset({"neutropenia", "fever"}): 2.0,        # 粒缺性发热
    frozenset({"thrombocytopenia", "bleeding"}): 1.8,
    frozenset({"fatigue", "anemia"}): 1.3,
    frozenset({"dyspnea", "cardiac_toxicity"}): 1.6,
    frozenset({"rash", "fever"}): 1.4,               # 药物过敏可能
}


class SymptomRiskItem(BaseModel):
    """单症状风险评分明细"""
    symptom_type: str
    ctcae_grade: int
    weight: float = Field(..., description="症状权重")
    urgency_factor: float = Field(..., description="紧迫因子")
    urgency_factor_type: UrgencyFactor
    raw_score: float = Field(..., description="grade × weight × urgency_factor")


class InteractionEffect(BaseModel):
    """症状交互效应"""
    symptom_pair: list[str]
    multiplier: float
    reason: str


class RiskScore(BaseModel):
    """多症状综合风险评分结果"""
    total_score: float = Field(..., description="综合风险分 = Σ(grade×weight×urgency) × interaction")
    normalized_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="归一化到 [0,1] 的风险分",
    )
    risk_level: RiskLevel
    urgency: UrgencyLevel
    items: list[SymptomRiskItem] = Field(..., description="各症状评分明细")
    interactions: list[InteractionEffect] = Field(
        default_factory=list, description="交互效应",
    )
    interaction_multiplier: float = Field(
        default=1.0, description="交互效应总乘数",
    )

    # 风险等级映射阈值
    THRESHOLD_LOW: float = 0.3
    THRESHOLD_MEDIUM: float = 0.6

    class Config:
        # 允许类属性
        arbitrary_types_allowed = True


# ============================================================
# 冲突解决
# ============================================================

class RuleHit(BaseModel):
    """单条规则命中记录"""
    rule_id: str
    rule_version: str
    rule_name: str
    priority: int
    priority_class: RulePriority
    risk_level: RiskLevel
    urgency: UrgencyLevel
    ctcae_grade: int
    symptom_type: str
    match_type: MatchType
    confidence: float
    patient_message: str
    clinician_message: str = ""
    tags: list[str] = Field(default_factory=list)


class ConflictResolution(BaseModel):
    """冲突解决结果"""
    final_risk_level: RiskLevel
    final_urgency: UrgencyLevel
    primary_rule: RuleHit = Field(..., description="主决策规则")
    all_hits: list[RuleHit] = Field(..., description="所有命中规则")
    conflicts_detected: list[str] = Field(
        default_factory=list, description="检测到的冲突描述",
    )
    resolution_strategy: str = Field(
        ..., description="冲突解决策略说明",
    )
    merged_tags: list[str] = Field(default_factory=list)
    should_contact_team: bool = Field(default=False)


# ============================================================
# 置信度
# ============================================================

class DecisionConfidence(BaseModel):
    """决策置信度"""
    rule_confidence: float = Field(..., ge=0.0, le=1.0, description="规则匹配置信度")
    llm_confidence: float | None = Field(None, ge=0.0, le=1.0, description="LLM置信度")
    combined_confidence: float = Field(..., ge=0.0, le=1.0, description="综合置信度")
    weight_rule: float = Field(default=0.7, description="规则权重 w1")
    weight_llm: float = Field(default=0.3, description="LLM权重 w2")
    is_low_confidence: bool = Field(default=False, description="是否低置信度")
    low_confidence_action: str | None = Field(
        None, description="低置信度时的处理策略",
    )
    details: str = Field(default="", description="置信度计算说明")


# ============================================================
# 审计链
# ============================================================

class AuditStep(BaseModel):
    """审计链中的单步记录"""
    step_index: int
    step_name: str = Field(..., description="步骤名称")
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    rules_evaluated: list[str] = Field(
        default_factory=list, description="本步骤评估的规则ID列表",
    )
    rules_matched: list[str] = Field(
        default_factory=list, description="本步骤命中的规则ID列表",
    )
    duration_ms: float = Field(default=0.0, description="步骤耗时(ms)")
    notes: str = Field(default="")


class AuditTrail(BaseModel):
    """完整决策审计链"""
    trail_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
    )
    assessment_id: str | None = None
    steps: list[AuditStep] = Field(default_factory=list)
    total_rules_evaluated: int = 0
    total_rules_matched: int = 0
    total_duration_ms: float = 0.0
    rule_snapshot_hash: str = Field(
        default="", description="规则快照hash，保证可复现",
    )
    engine_version: str = Field(default="0.1.0")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# 决策层最终输出
# ============================================================

class DecisionResult(BaseModel):
    """决策层最终输出 — 传递给执行层"""
    # 核心结果
    risk_level: RiskLevel
    urgency: UrgencyLevel
    should_contact_team: bool
    ctcae_grades: dict[str, int] = Field(
        ..., description="各症状CTCAE分级 {symptom_type: grade}",
    )
    # 评分
    risk_score: RiskScore
    # 冲突解决
    conflict_resolution: ConflictResolution
    # 置信度
    confidence: DecisionConfidence
    # 审计
    audit_trail: AuditTrail
    # 元数据
    symptom_grades: list[SymptomGrade] = Field(
        ..., description="各症状分级详情",
    )
    primary_rule_id: str
    matched_rule_ids: list[str]
    rule_versions: dict[str, str] = Field(
        ..., description="规则ID→版本号映射",
    )
    ai_enhanced: bool = False
    ai_degraded: bool = False
