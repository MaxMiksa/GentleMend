"""
风险评分算法 — 决策层核心组件

算法:
  1. 单症状 CTCAE 分级: 基于决策表匹配
  2. 多症状综合风险评分:
     risk_score = Σ(grade_i × weight_i × urgency_factor_i) × interaction_multiplier
  3. 归一化 + 风险等级映射

设计原则:
  - 安全优先: 粒缺性发热等致命副作用权重远高于脱发
  - 交互效应: 恶心+发热 > 单独恶心
  - 可解释: 每步计算都有明细记录
"""

from __future__ import annotations

import math
from typing import Any

from app.decision.schemas import (
    InteractionEffect,
    MatchType,
    RiskLevel,
    RiskScore,
    SymptomGrade,
    SymptomRiskItem,
    UrgencyFactor,
    UrgencyLevel,
    SYMPTOM_WEIGHTS,
    URGENCY_FACTOR_VALUES,
    SYMPTOM_INTERACTIONS,
)


# CTCAE 等级 → 风险等级映射
GRADE_TO_RISK: dict[int, RiskLevel] = {
    1: RiskLevel.LOW,
    2: RiskLevel.LOW,      # Grade 2 默认 low，但综合评分可能提升
    3: RiskLevel.MEDIUM,
    4: RiskLevel.HIGH,
    5: RiskLevel.HIGH,
}

# CTCAE 等级 → 默认紧急度
GRADE_TO_URGENCY: dict[int, UrgencyLevel] = {
    1: UrgencyLevel.SELF_MONITOR,
    2: UrgencyLevel.CONTACT_ROUTINE,
    3: UrgencyLevel.CONTACT_24H,
    4: UrgencyLevel.EMERGENCY,
    5: UrgencyLevel.EMERGENCY,
}

# 风险等级排序
RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}

URGENCY_ORDER: dict[UrgencyLevel, int] = {
    UrgencyLevel.SELF_MONITOR: 0,
    UrgencyLevel.CONTACT_ROUTINE: 1,
    UrgencyLevel.CONTACT_24H: 2,
    UrgencyLevel.EMERGENCY: 3,
}

# 归一化参数: 理论最大分（用于 sigmoid 归一化）
# 假设最坏情况: 3个 Grade 4 高权重症状同时急性发作
_MAX_THEORETICAL_SCORE = 4 * 5.0 * 2.0 * 3  # ~120


class RiskScorer:
    """
    风险评分引擎

    职责:
      1. 对每个症状进行 CTCAE 分级（基于决策表匹配结果）
      2. 计算多症状综合风险评分
      3. 考虑症状交互效应
      4. 映射到风险等级
    """

    def __init__(
        self,
        symptom_weights: dict[str, float] | None = None,
        urgency_factors: dict[UrgencyFactor, float] | None = None,
        interactions: dict[frozenset[str], float] | None = None,
        threshold_low: float = 0.3,
        threshold_medium: float = 0.6,
    ):
        self._weights = symptom_weights or SYMPTOM_WEIGHTS
        self._urgency_factors = urgency_factors or URGENCY_FACTOR_VALUES
        self._interactions = interactions or SYMPTOM_INTERACTIONS
        self._threshold_low = threshold_low
        self._threshold_medium = threshold_medium

    # ----------------------------------------------------------
    # 1. 单症状 CTCAE 分级
    # ----------------------------------------------------------

    def grade_single_symptom(
        self,
        symptom_type: str,
        facts: dict[str, Any],
        matched_rule: dict[str, Any] | None = None,
    ) -> SymptomGrade:
        """
        基于决策表匹配结果对单个症状进行 CTCAE 分级。

        Args:
            symptom_type: CTCAE 标准术语
            facts: 该症状的事实数据
            matched_rule: 规则引擎匹配到的规则（含 action 字段）

        Returns:
            SymptomGrade 分级结果
        """
        if matched_rule is None:
            # 无规则命中 → 默认 Grade 1
            return SymptomGrade(
                symptom_type=symptom_type,
                ctcae_grade=1,
                matched_rule_id="DEFAULT-G1",
                match_type=MatchType.FUZZY,
                match_confidence=0.3,
                matched_conditions={},
                risk_level=RiskLevel.LOW,
                urgency=UrgencyLevel.SELF_MONITOR,
                patient_message="请继续观察症状变化，如有加重请及时反馈。",
                clinician_message="",
            )

        action = matched_rule.get("action", {})
        grade = action.get("ctcae_grade", matched_rule.get("ctcae_grade", 1))
        risk_str = action.get("risk_level", "low")
        urgency_str = action.get("urgency", "self_monitor")

        risk_level = RiskLevel(risk_str)
        urgency = UrgencyLevel(urgency_str)

        return SymptomGrade(
            symptom_type=symptom_type,
            ctcae_grade=grade,
            matched_rule_id=matched_rule.get("rule_id", "UNKNOWN"),
            match_type=MatchType.EXACT,
            match_confidence=1.0,
            matched_conditions=facts,
            risk_level=risk_level,
            urgency=urgency,
            patient_message=action.get("patient_message_template", ""),
            clinician_message=action.get("clinician_message_template", ""),
        )

    # ----------------------------------------------------------
    # 2. 多症状综合风险评分
    # ----------------------------------------------------------

    def compute_risk_score(
        self,
        grades: list[SymptomGrade],
        urgency_factors: dict[str, UrgencyFactor] | None = None,
        drug_classes: list[str] | None = None,
    ) -> RiskScore:
        """
        多症状综合风险评分。

        公式: risk_score = Σ(grade_i × weight_i × urgency_factor_i) × interaction_multiplier

        Args:
            grades: 各症状的 CTCAE 分级结果
            urgency_factors: 各症状的紧迫因子 {symptom_type: UrgencyFactor}
            drug_classes: 患者当前用药类别（用于药物关联加权）

        Returns:
            RiskScore 综合评分结果
        """
        if not grades:
            return RiskScore(
                total_score=0.0,
                normalized_score=0.0,
                risk_level=RiskLevel.LOW,
                urgency=UrgencyLevel.SELF_MONITOR,
                items=[],
                interactions=[],
                interaction_multiplier=1.0,
            )

        urgency_factors = urgency_factors or {}
        items: list[SymptomRiskItem] = []

        # 2a. 计算每个症状的风险分
        for g in grades:
            weight = self._weights.get(g.symptom_type, 1.0)
            uf_type = urgency_factors.get(g.symptom_type, UrgencyFactor.STABLE)
            uf_value = self._urgency_factors[uf_type]
            raw = g.ctcae_grade * weight * uf_value

            items.append(SymptomRiskItem(
                symptom_type=g.symptom_type,
                ctcae_grade=g.ctcae_grade,
                weight=weight,
                urgency_factor=uf_value,
                urgency_factor_type=uf_type,
                raw_score=round(raw, 3),
            ))

        base_score = sum(item.raw_score for item in items)

        # 2b. 计算交互效应
        symptom_set = {g.symptom_type for g in grades}
        interactions: list[InteractionEffect] = []
        interaction_multiplier = 1.0

        for pair, multiplier in self._interactions.items():
            if pair.issubset(symptom_set):
                pair_list = sorted(pair)
                interactions.append(InteractionEffect(
                    symptom_pair=pair_list,
                    multiplier=multiplier,
                    reason=f"症状组合 {'+'.join(pair_list)} 存在交互效应",
                ))
                # 取最大交互乘数（不叠加，避免过度放大）
                interaction_multiplier = max(interaction_multiplier, multiplier)

        total_score = base_score * interaction_multiplier

        # 2c. Sigmoid 归一化到 [0, 1]
        normalized = self._sigmoid_normalize(total_score)

        # 2d. 映射风险等级
        risk_level = self._score_to_risk_level(normalized)

        # 2e. 取所有症状中最高紧急度
        max_urgency = max(
            (g.urgency for g in grades),
            key=lambda u: URGENCY_ORDER[u],
        )

        return RiskScore(
            total_score=round(total_score, 3),
            normalized_score=round(normalized, 4),
            risk_level=risk_level,
            urgency=max_urgency,
            items=items,
            interactions=interactions,
            interaction_multiplier=round(interaction_multiplier, 2),
        )

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _sigmoid_normalize(self, score: float) -> float:
        """
        使用修正 sigmoid 将原始分归一化到 [0, 1]。
        k 控制曲线陡峭度，midpoint 是 0.5 对应的原始分。
        """
        midpoint = _MAX_THEORETICAL_SCORE * 0.25  # ~30 分对应 0.5
        k = 0.08
        return 1.0 / (1.0 + math.exp(-k * (score - midpoint)))

    def _score_to_risk_level(self, normalized: float) -> RiskLevel:
        """归一化分 → 风险等级"""
        if normalized >= self._threshold_medium:
            return RiskLevel.HIGH
        if normalized >= self._threshold_low:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
