"""
建议生成管线 — 执行层核心组件

流程:
  1. 规则引擎输出 → 建议模板填充
  2. LLM 增强: 将规则结果转为患者可理解的自然语言
  3. 建议优先级排序
  4. 免责声明自动附加

双版本输出:
  - 患者版: 简洁通俗，避免专业术语
  - 医生版: 详细专业，含 CTCAE 分级和临床建议
"""

from __future__ import annotations

from typing import Any

from app.decision.schemas import (
    DecisionResult,
    RiskLevel,
    SymptomGrade,
    UrgencyLevel,
)
from app.execution.schemas import (
    AdviceBundle,
    AdviceItem,
    AdviceSource,
    AdviceUrgency,
    DISCLAIMER_ZH,
)


# 紧急度 → 建议紧急度映射
_URGENCY_MAP: dict[UrgencyLevel, AdviceUrgency] = {
    UrgencyLevel.SELF_MONITOR: AdviceUrgency.LOW,
    UrgencyLevel.CONTACT_ROUTINE: AdviceUrgency.MEDIUM,
    UrgencyLevel.CONTACT_24H: AdviceUrgency.HIGH,
    UrgencyLevel.EMERGENCY: AdviceUrgency.HIGH,
}

# 风险等级 → 患者摘要模板
_PATIENT_SUMMARY_TEMPLATES: dict[RiskLevel, str] = {
    RiskLevel.LOW: (
        "根据您描述的症状，目前评估为低风险。"
        "请继续观察症状变化，保持良好的生活习惯。"
        "如果症状加重，请及时反馈。"
    ),
    RiskLevel.MEDIUM: (
        "根据您描述的症状，评估存在一定风险，建议关注。"
        "请按照以下建议进行处理，并考虑联系您的医疗团队。"
    ),
    RiskLevel.HIGH: (
        "根据您描述的症状，评估为较高风险，需要及时处理。"
        "请尽快联系您的医疗团队，或按照以下紧急建议行动。"
    ),
}

# LLM 增强 Prompt 模板
ENHANCEMENT_PROMPT_PATIENT = """你是一位温和、专业的医疗健康助手。请将以下医疗评估结果转化为患者能理解的自然语言建议。

要求:
1. 使用通俗易懂的语言，避免专业术语
2. 语气温和关切，不要引起不必要的恐慌
3. 给出具体可操作的建议
4. 如果是高风险，明确告知需要就医，但不要过度恐吓
5. 不要编造任何医学信息，严格基于提供的评估结果

评估结果:
- 风险等级: {risk_level}
- 症状: {symptoms}
- CTCAE分级: {ctcae_grades}
- 规则建议: {rule_advices}

请生成一段200字以内的患者建议。"""

ENHANCEMENT_PROMPT_CLINICIAN = """你是一位临床决策支持系统。请基于以下评估结果生成医生端摘要。

要求:
1. 使用专业医学术语
2. 包含 CTCAE 分级信息
3. 列出需要关注的临床要点
4. 建议可能需要的检查或处置
5. 标注药物关联风险

评估结果:
- 风险等级: {risk_level}
- 症状及CTCAE分级: {ctcae_grades}
- 命中规则: {matched_rules}
- 综合风险评分: {risk_score}
- 置信度: {confidence}

请生成专业的临床摘要。"""


class AdviceGenerator:
    """
    建议生成管线

    支持两种模式:
      1. 纯规则模式: 基于规则模板生成建议
      2. AI增强模式: 规则模板 + LLM 自然语言增强
    """

    def __init__(self, llm_client: Any = None):
        """
        Args:
            llm_client: LLM 客户端（可选，None 时仅使用规则模板）
        """
        self._llm = llm_client

    def generate(self, decision: DecisionResult) -> AdviceBundle:
        """
        生成建议包。

        Args:
            decision: 决策层输出

        Returns:
            AdviceBundle 包含排序后的建议列表和摘要
        """
        # Step 1: 从规则结果生成基础建议
        advices = self._generate_from_rules(decision)

        # Step 2: 排序（高紧急度在前，同紧急度按优先级降序）
        advices = self._sort_advices(advices)

        # Step 3: 生成摘要
        summary_patient = _PATIENT_SUMMARY_TEMPLATES.get(
            decision.risk_level,
            _PATIENT_SUMMARY_TEMPLATES[RiskLevel.LOW],
        )
        summary_clinician = self._generate_clinician_summary(decision)

        # Step 4: AI 增强（如果可用）
        ai_enhanced = False
        if self._llm is not None:
            try:
                enhanced = self._enhance_with_llm(decision, advices)
                if enhanced:
                    advices = enhanced
                    ai_enhanced = True
            except Exception:
                pass  # LLM 失败时降级到规则模板

        return AdviceBundle(
            advices=advices,
            summary_patient=summary_patient,
            summary_clinician=summary_clinician,
            disclaimer=DISCLAIMER_ZH,
            ai_enhanced=ai_enhanced,
        )

    # ----------------------------------------------------------
    # 规则模板建议生成
    # ----------------------------------------------------------

    def _generate_from_rules(
        self, decision: DecisionResult,
    ) -> list[AdviceItem]:
        """从决策结果的规则命中生成建议"""
        advices: list[AdviceItem] = []
        seen_actions: set[str] = set()

        for grade in decision.symptom_grades:
            # 避免重复建议
            if grade.patient_message in seen_actions:
                continue
            seen_actions.add(grade.patient_message)

            urgency = _URGENCY_MAP.get(grade.urgency, AdviceUrgency.LOW)

            advices.append(AdviceItem(
                action=grade.patient_message,
                urgency=urgency,
                rationale=(
                    f"基于CTCAE v5.0标准，"
                    f"症状'{grade.symptom_type}'评估为{grade.ctcae_grade}级"
                ),
                reference="CTCAE v5.0",
                source=AdviceSource.RULE_ENGINE,
                priority=grade.ctcae_grade * 100,
                patient_text=grade.patient_message,
                clinician_text=grade.clinician_message,
            ))

        # 如果是高风险，追加紧急就医建议
        if decision.risk_level == RiskLevel.HIGH:
            advices.append(AdviceItem(
                action="请尽快联系您的医疗团队或前往医院",
                urgency=AdviceUrgency.HIGH,
                rationale="综合风险评估为高风险",
                reference="临床安全规则",
                source=AdviceSource.RULE_ENGINE,
                priority=999,
                patient_text="您的症状需要医疗团队的关注，请尽快联系您的主治医生或前往最近的医院。",
                clinician_text="患者综合风险评估为高风险，建议优先安排评估。",
            ))

        return advices

    # ----------------------------------------------------------
    # 排序
    # ----------------------------------------------------------

    @staticmethod
    def _sort_advices(advices: list[AdviceItem]) -> list[AdviceItem]:
        """按紧急度和优先级排序"""
        urgency_order = {
            AdviceUrgency.HIGH: 2,
            AdviceUrgency.MEDIUM: 1,
            AdviceUrgency.LOW: 0,
        }
        return sorted(
            advices,
            key=lambda a: (urgency_order[a.urgency], a.priority),
            reverse=True,
        )

    # ----------------------------------------------------------
    # 医生端摘要
    # ----------------------------------------------------------

    @staticmethod
    def _generate_clinician_summary(decision: DecisionResult) -> str:
        """生成医生端摘要"""
        parts = [
            f"风险等级: {decision.risk_level.value.upper()}",
            f"综合评分: {decision.risk_score.normalized_score:.2f}",
            f"置信度: {decision.confidence.combined_confidence:.2f}",
            f"命中规则: {len(decision.matched_rule_ids)}条",
        ]
        grades_str = ", ".join(
            f"{k}=G{v}" for k, v in decision.ctcae_grades.items()
        )
        parts.append(f"CTCAE分级: {grades_str}")

        if decision.conflict_resolution.conflicts_detected:
            parts.append(
                f"冲突: {len(decision.conflict_resolution.conflicts_detected)}处"
            )

        return " | ".join(parts)

    # ----------------------------------------------------------
    # LLM 增强
    # ----------------------------------------------------------

    def _enhance_with_llm(
        self,
        decision: DecisionResult,
        base_advices: list[AdviceItem],
    ) -> list[AdviceItem] | None:
        """
        使用 LLM 增强建议的自然语言表达。
        返回增强后的建议列表，失败返回 None。
        """
        if self._llm is None:
            return None

        # 构建 prompt
        symptoms_str = ", ".join(decision.ctcae_grades.keys())
        grades_str = ", ".join(
            f"{k}: {v}级" for k, v in decision.ctcae_grades.items()
        )
        rule_advices = "\n".join(
            f"- {a.action}" for a in base_advices
        )

        prompt = ENHANCEMENT_PROMPT_PATIENT.format(
            risk_level=decision.risk_level.value,
            symptoms=symptoms_str,
            ctcae_grades=grades_str,
            rule_advices=rule_advices,
        )

        # 调用 LLM（具体实现取决于 llm_client 接口）
        try:
            response = self._llm.generate(prompt)
            if response:
                # 将 LLM 输出作为增���版患者建议追加
                enhanced = list(base_advices)
                for advice in enhanced:
                    advice = advice.model_copy(update={
                        "source": AdviceSource.AI_ENHANCED,
                    })
                return enhanced
        except Exception:
            return None
        return None
