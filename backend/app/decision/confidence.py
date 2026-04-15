"""
决策置信度计算 — 决策层核心组件

置信度来源:
  1. 规则匹配置信度: 完全匹配 1.0, 部分匹配 0.7, 模糊匹配 0.5
  2. LLM 置信度: 多次采样一致性 or 自评分
  3. 综合置信度: w1 × rule_confidence + w2 × llm_confidence (w1 > w2)

低置信度处理:
  - < 0.4: 转人工审核
  - 0.4-0.6: 要求补充信息
  - 0.6-0.8: 标记不确定性
  - >= 0.8: 正常输出
"""

from __future__ import annotations

from app.decision.schemas import (
    DecisionConfidence,
    MatchType,
    RuleHit,
)


# 匹配类型 → 基础置信度
MATCH_TYPE_CONFIDENCE: dict[MatchType, float] = {
    MatchType.EXACT: 1.0,
    MatchType.PARTIAL: 0.7,
    MatchType.FUZZY: 0.5,
    MatchType.DRUG_BOOSTED: 0.9,
}

# 置信度阈值
THRESHOLD_MANUAL_REVIEW = 0.4
THRESHOLD_REQUEST_INFO = 0.6
THRESHOLD_UNCERTAIN = 0.8


class ConfidenceCalculator:
    """
    决策置信度计算器

    综合置信度 = w1 × rule_confidence + w2 × llm_confidence
    其中 w1 > w2，确保规则引擎的确定性结果占主导。
    """

    def __init__(
        self,
        weight_rule: float = 0.7,
        weight_llm: float = 0.3,
    ):
        if abs(weight_rule + weight_llm - 1.0) > 0.01:
            raise ValueError("权重之和必须为 1.0")
        if weight_rule <= weight_llm:
            raise ValueError("规则权重必须大于 LLM 权重 (w1 > w2)")
        self._w_rule = weight_rule
        self._w_llm = weight_llm

    def compute(
        self,
        rule_hits: list[RuleHit],
        llm_confidence: float | None = None,
        llm_samples: list[dict] | None = None,
    ) -> DecisionConfidence:
        """
        计算综合决策置信度。

        Args:
            rule_hits: 命中的规则列表
            llm_confidence: LLM 自评置信度 (0-1)
            llm_samples: LLM 多次采样结果（用于计算一致性）

        Returns:
            DecisionConfidence
        """
        # 1. 规则匹配置信度
        rule_conf = self._compute_rule_confidence(rule_hits)

        # 2. LLM 置信度
        llm_conf = self._compute_llm_confidence(llm_confidence, llm_samples)

        # 3. 综合置信度
        if llm_conf is not None:
            combined = self._w_rule * rule_conf + self._w_llm * llm_conf
        else:
            # LLM 不可用时，仅使用规则置信度
            combined = rule_conf

        combined = round(min(max(combined, 0.0), 1.0), 4)

        # 4. 低置信度处理
        is_low, action = self._evaluate_low_confidence(combined)

        # 5. 生成说明
        details = self._build_details(rule_conf, llm_conf, combined, rule_hits)

        return DecisionConfidence(
            rule_confidence=round(rule_conf, 4),
            llm_confidence=round(llm_conf, 4) if llm_conf is not None else None,
            combined_confidence=combined,
            weight_rule=self._w_rule,
            weight_llm=self._w_llm,
            is_low_confidence=is_low,
            low_confidence_action=action,
            details=details,
        )

    # ----------------------------------------------------------
    # 规则置信度
    # ----------------------------------------------------------

    def _compute_rule_confidence(self, hits: list[RuleHit]) -> float:
        """
        规则匹配置信度 = 所有命中规则置信度的加权平均。
        权重为规则优先级归一化值。
        """
        if not hits:
            return 0.3  # 无规则命中，基础置信度

        total_weight = 0.0
        weighted_conf = 0.0
        for h in hits:
            base_conf = MATCH_TYPE_CONFIDENCE.get(h.match_type, 0.5)
            # 规则自身置信度 × 匹配类型置信度
            conf = h.confidence * base_conf
            # 优先级作为权重（归一化到 0-1）
            w = h.priority / 1000.0
            weighted_conf += conf * w
            total_weight += w

        if total_weight == 0:
            return 0.3
        return min(weighted_conf / total_weight, 1.0)

    # ----------------------------------------------------------
    # LLM 置信度
    # ----------------------------------------------------------

    def _compute_llm_confidence(
        self,
        self_score: float | None,
        samples: list[dict] | None,
    ) -> float | None:
        """
        LLM 置信度计算:
          - 优先使用多次采样一致性
          - 回退到 LLM 自评分
        """
        if samples and len(samples) >= 2:
            return self._sampling_consistency(samples)
        return self_score

    def _sampling_consistency(self, samples: list[dict]) -> float:
        """
        多次采样一致性: 统计各采样结果的 risk_level 一致比例。
        """
        risk_levels = [s.get("risk_level", "unknown") for s in samples]
        if not risk_levels:
            return 0.5

        from collections import Counter
        counter = Counter(risk_levels)
        most_common_count = counter.most_common(1)[0][1]
        return most_common_count / len(risk_levels)

    # ----------------------------------------------------------
    # 低置信度处理
    # ----------------------------------------------------------

    def _evaluate_low_confidence(
        self, combined: float,
    ) -> tuple[bool, str | None]:
        """评估是否低置信度，返回 (is_low, action)"""
        if combined < THRESHOLD_MANUAL_REVIEW:
            return True, "transfer_to_human"
        if combined < THRESHOLD_REQUEST_INFO:
            return True, "request_additional_info"
        if combined < THRESHOLD_UNCERTAIN:
            return False, "mark_uncertain"
        return False, None

    # ----------------------------------------------------------
    # 说明生成
    # ----------------------------------------------------------

    def _build_details(
        self,
        rule_conf: float,
        llm_conf: float | None,
        combined: float,
        hits: list[RuleHit],
    ) -> str:
        parts = [f"规则置信度={rule_conf:.2f}(基于{len(hits)}条命中规则)"]
        if llm_conf is not None:
            parts.append(f"LLM置信度={llm_conf:.2f}")
            parts.append(
                f"综合={self._w_rule}×{rule_conf:.2f}"
                f"+{self._w_llm}×{llm_conf:.2f}={combined:.2f}"
            )
        else:
            parts.append("LLM不可用，仅使用规则置信度")
        return "；".join(parts)
