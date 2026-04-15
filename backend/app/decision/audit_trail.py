"""
决策审计链生成 — 决策层核心组件

每步决策的完整记录: 输入 → 规则命中 → 中间计算 → 最终结果
生成 Evidence 实体，构建可追溯的决策路径。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.decision.schemas import (
    AuditStep,
    AuditTrail,
    ConflictResolution,
    DecisionConfidence,
    RiskScore,
    SymptomGrade,
)


class AuditTrailBuilder:
    """
    决策审计链构建器

    使用方式:
        builder = AuditTrailBuilder(engine_version="0.1.0")
        builder.start(assessment_id, rule_snapshot_hash)
        builder.record_grading(...)
        builder.record_scoring(...)
        builder.record_conflict_resolution(...)
        builder.record_confidence(...)
        trail = builder.build()
    """

    def __init__(self, engine_version: str = "0.1.0"):
        self._engine_version = engine_version
        self._steps: list[AuditStep] = []
        self._assessment_id: str | None = None
        self._rule_snapshot_hash: str = ""
        self._start_time: float = 0.0
        self._step_counter: int = 0

    def start(
        self,
        assessment_id: str | None = None,
        rule_snapshot_hash: str = "",
    ) -> None:
        """开始构建审计链"""
        self._assessment_id = assessment_id
        self._rule_snapshot_hash = rule_snapshot_hash
        self._start_time = time.monotonic()
        self._steps = []
        self._step_counter = 0

    def record_grading(
        self,
        input_symptoms: list[dict[str, Any]],
        grades: list[SymptomGrade],
        rules_evaluated: list[str],
        duration_ms: float,
    ) -> None:
        """记录 CTCAE 分级步骤"""
        self._step_counter += 1
        self._steps.append(AuditStep(
            step_index=self._step_counter,
            step_name="CTCAE分级",
            input_data={"symptoms": input_symptoms},
            output_data={
                "grades": {
                    g.symptom_type: {
                        "grade": g.ctcae_grade,
                        "rule_id": g.matched_rule_id,
                        "match_type": g.match_type.value,
                        "confidence": g.match_confidence,
                    }
                    for g in grades
                },
            },
            rules_evaluated=rules_evaluated,
            rules_matched=[g.matched_rule_id for g in grades],
            duration_ms=duration_ms,
            notes=f"对{len(input_symptoms)}个症状完成CTCAE分级",
        ))

    def record_scoring(
        self,
        risk_score: RiskScore,
        duration_ms: float,
    ) -> None:
        """记录风险评分步骤"""
        self._step_counter += 1
        self._steps.append(AuditStep(
            step_index=self._step_counter,
            step_name="综合风险评分",
            input_data={
                "items": [
                    {
                        "symptom": item.symptom_type,
                        "grade": item.ctcae_grade,
                        "weight": item.weight,
                        "urgency_factor": item.urgency_factor,
                    }
                    for item in risk_score.items
                ],
            },
            output_data={
                "total_score": risk_score.total_score,
                "normalized_score": risk_score.normalized_score,
                "risk_level": risk_score.risk_level.value,
                "interaction_multiplier": risk_score.interaction_multiplier,
                "interactions": [
                    {"pair": ie.symptom_pair, "multiplier": ie.multiplier}
                    for ie in risk_score.interactions
                ],
            },
            duration_ms=duration_ms,
            notes=(
                f"综合评分={risk_score.total_score:.2f}，"
                f"归一化={risk_score.normalized_score:.4f}，"
                f"风险等级={risk_score.risk_level.value}"
            ),
        ))

    def record_conflict_resolution(
        self,
        resolution: ConflictResolution,
        duration_ms: float,
    ) -> None:
        """记录冲突解决步骤"""
        self._step_counter += 1
        self._steps.append(AuditStep(
            step_index=self._step_counter,
            step_name="冲突解决",
            input_data={
                "total_hits": len(resolution.all_hits),
                "hit_rule_ids": [h.rule_id for h in resolution.all_hits],
            },
            output_data={
                "final_risk_level": resolution.final_risk_level.value,
                "final_urgency": resolution.final_urgency.value,
                "primary_rule": resolution.primary_rule.rule_id,
                "conflicts": resolution.conflicts_detected,
                "strategy": resolution.resolution_strategy,
                "should_contact_team": resolution.should_contact_team,
            },
            rules_evaluated=[h.rule_id for h in resolution.all_hits],
            rules_matched=[h.rule_id for h in resolution.all_hits],
            duration_ms=duration_ms,
            notes=resolution.resolution_strategy,
        ))

    def record_confidence(
        self,
        confidence: DecisionConfidence,
        duration_ms: float,
    ) -> None:
        """记录置信度计算步骤"""
        self._step_counter += 1
        self._steps.append(AuditStep(
            step_index=self._step_counter,
            step_name="置信度计算",
            input_data={
                "rule_confidence": confidence.rule_confidence,
                "llm_confidence": confidence.llm_confidence,
                "weight_rule": confidence.weight_rule,
                "weight_llm": confidence.weight_llm,
            },
            output_data={
                "combined_confidence": confidence.combined_confidence,
                "is_low_confidence": confidence.is_low_confidence,
                "action": confidence.low_confidence_action,
            },
            duration_ms=duration_ms,
            notes=confidence.details,
        ))

    def record_custom_step(
        self,
        step_name: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        duration_ms: float = 0.0,
        notes: str = "",
    ) -> None:
        """记录自定义步骤"""
        self._step_counter += 1
        self._steps.append(AuditStep(
            step_index=self._step_counter,
            step_name=step_name,
            input_data=input_data,
            output_data=output_data,
            duration_ms=duration_ms,
            notes=notes,
        ))

    def build(self) -> AuditTrail:
        """构建最终审计链"""
        total_duration = (time.monotonic() - self._start_time) * 1000
        total_evaluated = sum(
            len(s.rules_evaluated) for s in self._steps
        )
        total_matched = sum(
            len(s.rules_matched) for s in self._steps
        )

        return AuditTrail(
            assessment_id=self._assessment_id,
            steps=list(self._steps),
            total_rules_evaluated=total_evaluated,
            total_rules_matched=total_matched,
            total_duration_ms=round(total_duration, 2),
            rule_snapshot_hash=self._rule_snapshot_hash,
            engine_version=self._engine_version,
        )

    # ----------------------------------------------------------
    # Evidence 实体生成
    # ----------------------------------------------------------

    @staticmethod
    def generate_evidences(
        trail: AuditTrail,
        grades: list[SymptomGrade],
    ) -> list[dict[str, Any]]:
        """
        从审计链和分级结果生成 Evidence 实体列表。
        每条命中规则生成一个 Evidence。
        """
        evidences: list[dict[str, Any]] = []
        for g in grades:
            evidences.append({
                "rule_id": g.matched_rule_id,
                "rule_version": "1.0.0",
                "rule_name": g.symptom_type,
                "description": (
                    f"症状'{g.symptom_type}'匹配规则{g.matched_rule_id}，"
                    f"CTCAE {g.ctcae_grade}级，"
                    f"匹配类型={g.match_type.value}，"
                    f"置信度={g.match_confidence}"
                ),
                "confidence": g.match_confidence,
                "source": "rule_engine",
                "matched_conditions": g.matched_conditions,
                "audit_trail_id": trail.trail_id,
            })
        return evidences
