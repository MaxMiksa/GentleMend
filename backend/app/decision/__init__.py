"""
浅愈(GentleMend) — 决策层 (Decision Layer)

职责：基于感知层输出的结构化症状数据，通过规则引擎 + LLM辅助
完成 CTCAE 分级、风险评分、冲突解决、置信度计算，生成可审计的决策结果。

核心组件:
  - RiskScorer: 风险评分算法（单症状分级 + 多症状综合评分）
  - ConflictResolver: 多规则冲突解决引擎
  - ConfidenceCalculator: 决策置信度计算
  - AuditTrailBuilder: 决策审计链生成
  - DecisionEngine: 决策层总编排
"""

from app.decision.schemas import (
    SymptomGrade,
    RiskScore,
    ConflictResolution,
    DecisionConfidence,
    AuditTrail,
    DecisionResult,
)
from app.decision.risk_scorer import RiskScorer
from app.decision.conflict_resolver import ConflictResolver
from app.decision.confidence import ConfidenceCalculator
from app.decision.audit_trail import AuditTrailBuilder
from app.decision.engine import DecisionEngine

__all__ = [
    "SymptomGrade",
    "RiskScore",
    "ConflictResolution",
    "DecisionConfidence",
    "AuditTrail",
    "DecisionResult",
    "RiskScorer",
    "ConflictResolver",
    "ConfidenceCalculator",
    "AuditTrailBuilder",
    "DecisionEngine",
]
