"""
不可变快照生成 — 执行层核心组件

Assessment 聚合根的最终状态冻结:
  - 包含完整的输入、决策、建议、审计信息
  - 计算内容 hash 保证完整性
  - 版本号递增，旧版本不可修改
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.decision.schemas import DecisionResult
from app.execution.schemas import (
    AdviceBundle,
    AssessmentSnapshot,
    CollaborationRequest,
    DISCLAIMER_ZH,
)


class SnapshotBuilder:
    """
    不可变快照构建器

    将决策结果 + 建议 + 协同请求组装为完整的 AssessmentSnapshot，
    计算 content_hash 后冻结。
    """

    def __init__(self, engine_version: str = "0.1.0"):
        self._engine_version = engine_version

    def build(
        self,
        assessment_id: str,
        original_description: str,
        symptoms_structured: list[dict[str, Any]],
        decision: DecisionResult,
        advice_bundle: AdviceBundle,
        version: int = 1,
        ai_model_version: str | None = None,
        ai_prompt_version: str | None = None,
    ) -> AssessmentSnapshot:
        """
        构建并冻结不可变快照。

        Args:
            assessment_id: 评估ID
            original_description: 患者原始描述
            symptoms_structured: 结构化症状列表
            decision: 决策层输出
            advice_bundle: 建议包
            version: 版本号（追加新版本时递增）
            ai_model_version: AI 模型版本
            ai_prompt_version: AI Prompt 版本

        Returns:
            冻结后的 AssessmentSnapshot（含 content_hash）
        """
        # 序列化建议
        advices_data = [
            {
                "advice_id": a.advice_id,
                "action": a.action,
                "urgency": a.urgency.value,
                "rationale": a.rationale,
                "reference": a.reference,
                "source": a.source.value,
                "priority": a.priority,
                "patient_text": a.patient_text,
                "clinician_text": a.clinician_text,
            }
            for a in advice_bundle.advices
        ]

        # 序列化依据
        from app.decision.audit_trail import AuditTrailBuilder
        evidences_data = AuditTrailBuilder.generate_evidences(
            decision.audit_trail,
            decision.symptom_grades,
        )

        snapshot = AssessmentSnapshot(
            assessment_id=assessment_id,
            version=version,
            original_description=original_description,
            symptoms_structured=symptoms_structured,
            risk_level=decision.risk_level.value,
            urgency=decision.urgency.value,
            should_contact_team=decision.should_contact_team,
            ctcae_grades=decision.ctcae_grades,
            overall_risk_score=decision.risk_score.total_score,
            normalized_risk_score=decision.risk_score.normalized_score,
            advices=advices_data,
            evidences=evidences_data,
            matched_rule_ids=decision.matched_rule_ids,
            rule_versions=decision.rule_versions,
            engine_version=self._engine_version,
            audit_trail_id=decision.audit_trail.trail_id,
            confidence=decision.confidence.combined_confidence,
            ai_enhanced=decision.ai_enhanced,
            ai_degraded=decision.ai_degraded,
            ai_model_version=ai_model_version,
            ai_prompt_version=ai_prompt_version,
            disclaimer=DISCLAIMER_ZH,
        )

        # 冻结: 计算 content_hash
        return snapshot.freeze()

    @staticmethod
    def verify_integrity(snapshot: AssessmentSnapshot) -> bool:
        """验证快照完整性（hash 校验）"""
        expected = snapshot.compute_hash()
        return expected == snapshot.content_hash

    @staticmethod
    def next_version(
        previous: AssessmentSnapshot,
    ) -> int:
        """计算下一个版本号"""
        return previous.version + 1
