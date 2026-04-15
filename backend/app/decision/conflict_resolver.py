"""
多规则冲突解决引擎 — 决策层核心组件

冲突解决策略:
  1. 同一症状多规则匹配 → 取最高严重度
  2. 规则结论矛盾 → 优先级排序: 安全规则 > 指南规则 > 经验规则
  3. 多症状交互效应 → 组合风险提升
  4. 药物-副作用关联 → 优先级加权

设计原则:
  - 安全优先: 任何冲突场景都取更安全（更高风险）的结论
  - 完全可追溯: 每次冲突解决都记录原因
"""

from __future__ import annotations

from typing import Any

from app.decision.schemas import (
    ConflictResolution,
    MatchType,
    RiskLevel,
    RuleHit,
    RulePriority,
    UrgencyLevel,
    SYMPTOM_INTERACTIONS,
)


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


def _classify_priority(priority: int) -> RulePriority:
    """根据数值优先级分类"""
    if priority >= 900:
        return RulePriority.SAFETY
    if priority >= 700:
        return RulePriority.GUIDELINE
    if priority >= 500:
        return RulePriority.CONSENSUS
    return RulePriority.EMPIRICAL


PRIORITY_CLASS_ORDER: dict[RulePriority, int] = {
    RulePriority.EMPIRICAL: 0,
    RulePriority.CONSENSUS: 1,
    RulePriority.GUIDELINE: 2,
    RulePriority.SAFETY: 3,
}


# 药物-副作用关联表（简化版，完整版从数据库加载）
DRUG_ASSOCIATIONS: dict[str, dict[str, int]] = {
    "anthracycline": {"cardiac_toxicity": 80, "nausea": 50},
    "taxane": {"peripheral_neuropathy": 50, "neutropenia": 50, "allergic_reaction": 50},
    "trastuzumab": {"cardiac_toxicity": 80},
    "cdk4_6_inhibitor": {"neutropenia": 50, "diarrhea": 50},
    "aromatase_inhibitor": {"arthralgia": 30, "hot_flash": 30},
    "tamoxifen": {"thromboembolism": 50, "hot_flash": 30},
}


class ConflictResolver:
    """
    多规则冲突解决引擎

    处理场景:
      A. 同一症状被多条规则命中 → 取最高严重度
      B. 不同规则给出矛盾结论 → 按优先级类别排序
      C. 多症状交互效应 → 组合风险提升
      D. 药物关联 → 优先级 boost
    """

    def __init__(
        self,
        drug_associations: dict[str, dict[str, int]] | None = None,
        interaction_table: dict[frozenset[str], float] | None = None,
    ):
        self._drug_assoc = drug_associations or DRUG_ASSOCIATIONS
        self._interactions = interaction_table or SYMPTOM_INTERACTIONS

    def resolve(
        self,
        matched_rules: list[dict[str, Any]],
        patient_drug_classes: list[str] | None = None,
    ) -> ConflictResolution:
        """
        执行完整的冲突解决流程。

        Args:
            matched_rules: 规则引擎返回的所有命中规则（原始 dict）
            patient_drug_classes: 患者当前用药类别

        Returns:
            ConflictResolution 冲突解决结果
        """
        if not matched_rules:
            return self._empty_resolution()

        # Step 1: 转换为 RuleHit 对象
        hits = [self._to_rule_hit(r) for r in matched_rules]

        # Step 2: 药物关联优先级 boost
        if patient_drug_classes:
            hits = self._apply_drug_boost(hits, patient_drug_classes)

        # Step 3: 同症状冲突解决 — 取最高严重度
        hits, symptom_conflicts = self._resolve_same_symptom(hits)

        # Step 4: 跨症状矛盾解决 — 按优先级类别排序
        hits, priority_conflicts = self._resolve_priority_conflicts(hits)

        # Step 5: 多症状交互效应检测
        interaction_notes = self._detect_interactions(hits)

        # Step 6: 确定最终结果
        all_conflicts = symptom_conflicts + priority_conflicts + interaction_notes

        final_risk = max(
            hits, key=lambda h: RISK_ORDER[h.risk_level],
        ).risk_level

        final_urgency = max(
            hits, key=lambda h: URGENCY_ORDER[h.urgency],
        ).urgency

        primary = max(
            hits,
            key=lambda h: (
                RISK_ORDER[h.risk_level],
                PRIORITY_CLASS_ORDER[h.priority_class],
                h.priority,
            ),
        )

        merged_tags = list(dict.fromkeys(
            tag for h in hits for tag in h.tags
        ))

        should_contact = (
            final_urgency in (UrgencyLevel.CONTACT_24H, UrgencyLevel.EMERGENCY)
            or final_risk == RiskLevel.HIGH
        )

        strategy = self._describe_strategy(
            len(hits), len(all_conflicts), primary,
        )

        return ConflictResolution(
            final_risk_level=final_risk,
            final_urgency=final_urgency,
            primary_rule=primary,
            all_hits=hits,
            conflicts_detected=all_conflicts,
            resolution_strategy=strategy,
            merged_tags=merged_tags,
            should_contact_team=should_contact,
        )

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _to_rule_hit(self, rule: dict[str, Any]) -> RuleHit:
        """将原始规则 dict 转换为 RuleHit"""
        action = rule.get("action", {})
        priority = rule.get("priority", 0)
        return RuleHit(
            rule_id=rule.get("rule_id", "UNKNOWN"),
            rule_version=rule.get("version", "0.0.0"),
            rule_name=rule.get("name", ""),
            priority=priority,
            priority_class=_classify_priority(priority),
            risk_level=RiskLevel(action.get("risk_level", "low")),
            urgency=UrgencyLevel(action.get("urgency", "self_monitor")),
            ctcae_grade=action.get("ctcae_grade", rule.get("ctcae_grade", 1)),
            symptom_type=rule.get("ctcae_term", rule.get("category", "")),
            match_type=MatchType.EXACT,
            confidence=1.0,
            patient_message=action.get("patient_message_template", ""),
            clinician_message=action.get("clinician_message_template", ""),
            tags=action.get("tags", []),
        )

    def _apply_drug_boost(
        self, hits: list[RuleHit], drug_classes: list[str],
    ) -> list[RuleHit]:
        """药物关联优先级 boost"""
        boosted: list[RuleHit] = []
        for h in hits:
            boost = 0
            for dc in drug_classes:
                assoc = self._drug_assoc.get(dc, {})
                boost = max(boost, assoc.get(h.symptom_type, 0))
            if boost > 0:
                h = h.model_copy(update={
                    "priority": h.priority + boost,
                    "priority_class": _classify_priority(h.priority + boost),
                    "match_type": MatchType.DRUG_BOOSTED,
                })
            boosted.append(h)
        return boosted

    def _resolve_same_symptom(
        self, hits: list[RuleHit],
    ) -> tuple[list[RuleHit], list[str]]:
        """
        同一症状多规则���中 → 每个症状只保留最高严重度的规则。
        """
        conflicts: list[str] = []
        by_symptom: dict[str, list[RuleHit]] = {}
        for h in hits:
            by_symptom.setdefault(h.symptom_type, []).append(h)

        resolved: list[RuleHit] = []
        for symptom, group in by_symptom.items():
            if len(group) > 1:
                group.sort(key=lambda h: (
                    RISK_ORDER[h.risk_level],
                    h.ctcae_grade,
                    h.priority,
                ), reverse=True)
                winner = group[0]
                losers = group[1:]
                loser_ids = [l.rule_id for l in losers]
                conflicts.append(
                    f"症状'{symptom}'有{len(group)}条规则命中，"
                    f"取最高严重度 {winner.rule_id}(G{winner.ctcae_grade})，"
                    f"覆盖 {loser_ids}"
                )
                resolved.append(winner)
            else:
                resolved.append(group[0])

        return resolved, conflicts

    def _resolve_priority_conflicts(
        self, hits: list[RuleHit],
    ) -> tuple[list[RuleHit], list[str]]:
        """
        规则结论矛盾时按优先级类别排序:
        安全规则 > 指南规则 > 专家共识 > 经验规则

        如果安全规则说 HIGH 但经验规则说 LOW，以安全规则为准。
        """
        conflicts: list[str] = []
        if len(hits) <= 1:
            return hits, conflicts

        risk_levels = {h.risk_level for h in hits}
        if len(risk_levels) > 1:
            # 存在不同风险等级的规则
            highest = max(hits, key=lambda h: (
                PRIORITY_CLASS_ORDER[h.priority_class],
                RISK_ORDER[h.risk_level],
            ))
            lowest = min(hits, key=lambda h: (
                PRIORITY_CLASS_ORDER[h.priority_class],
                RISK_ORDER[h.risk_level],
            ))
            if highest.risk_level != lowest.risk_level:
                conflicts.append(
                    f"规则结论矛盾: {highest.rule_id}({highest.priority_class.value})"
                    f"→{highest.risk_level.value} vs "
                    f"{lowest.rule_id}({lowest.priority_class.value})"
                    f"→{lowest.risk_level.value}，"
                    f"采用高优先级规则 {highest.rule_id}"
                )

        return hits, conflicts

    def _detect_interactions(self, hits: list[RuleHit]) -> list[str]:
        """检测多症状交互效应"""
        notes: list[str] = []
        symptom_set = {h.symptom_type for h in hits}

        for pair, multiplier in self._interactions.items():
            if pair.issubset(symptom_set):
                pair_str = " + ".join(sorted(pair))
                notes.append(
                    f"症状交互效应: {pair_str} 组合风险乘数 ×{multiplier}"
                )
        return notes

    def _describe_strategy(
        self, total_hits: int, total_conflicts: int, primary: RuleHit,
    ) -> str:
        """生成冲突解决策略说明"""
        parts = [f"共{total_hits}条规则命中"]
        if total_conflicts > 0:
            parts.append(f"检测到{total_conflicts}处冲突")
        parts.append(
            f"主决策规则: {primary.rule_id}"
            f"({primary.priority_class.value}, priority={primary.priority})"
        )
        parts.append("策略: 安全优先，取最高风险等级和最紧急处置")
        return "；".join(parts)

    def _empty_resolution(self) -> ConflictResolution:
        """无规则命中时的默认结果"""
        default_hit = RuleHit(
            rule_id="DEFAULT-NO-MATCH",
            rule_version="0.0.0",
            rule_name="无规则命中默认",
            priority=0,
            priority_class=RulePriority.EMPIRICAL,
            risk_level=RiskLevel.LOW,
            urgency=UrgencyLevel.SELF_MONITOR,
            ctcae_grade=1,
            symptom_type="unknown",
            match_type=MatchType.FUZZY,
            confidence=0.3,
            patient_message="请继续观察症状变化，如有加重请及时反馈。",
        )
        return ConflictResolution(
            final_risk_level=RiskLevel.LOW,
            final_urgency=UrgencyLevel.SELF_MONITOR,
            primary_rule=default_hit,
            all_hits=[default_hit],
            resolution_strategy="无规则命中，返回默认低风险评估",
            should_contact_team=False,
        )
