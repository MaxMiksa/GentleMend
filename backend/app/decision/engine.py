"""
决策引擎 — 决策层总编排

编排流程:
  1. 接收感知层输出的结构化症状
  2. 调用规则引擎进行 CTCAE 分级
  3. 计算多症状综合风险评分
  4. 执行冲突解决
  5. 计算决策置信度
  6. 生成审计链
  7. 输出 DecisionResult 给执行层
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from app.decision.audit_trail import AuditTrailBuilder
from app.decision.confidence import ConfidenceCalculator
from app.decision.conflict_resolver import ConflictResolver
from app.decision.risk_scorer import RiskScorer
from app.decision.schemas import (
    DecisionResult,
    RiskLevel,
    SymptomGrade,
    UrgencyFactor,
    UrgencyLevel,
)


class RuleEngineProtocol(Protocol):
    """规则引擎协议 — 决策层依赖的接口"""

    def evaluate(
        self, symptoms: list[dict[str, Any]], snapshot_hash: str,
    ) -> list[dict[str, Any]]:
        """评估症状，返回命中规则列表"""
        ...

    def get_snapshot_hash(self) -> str:
        """获取当前规则快照 hash"""
        ...


class DecisionEngine:
    """
    决策层总编排引擎

    协调 RiskScorer、ConflictResolver、ConfidenceCalculator、AuditTrailBuilder
    完成从结构化症状到 DecisionResult 的完整决策流程。
    """

    def __init__(
        self,
        rule_engine: RuleEngineProtocol | None = None,
        risk_scorer: RiskScorer | None = None,
        conflict_resolver: ConflictResolver | None = None,
        confidence_calculator: ConfidenceCalculator | None = None,
        engine_version: str = "0.1.0",
    ):
        self._rule_engine = rule_engine
        self._scorer = risk_scorer or RiskScorer()
        self._resolver = conflict_resolver or ConflictResolver()
        self._confidence = confidence_calculator or ConfidenceCalculator()
        self._engine_version = engine_version

    def decide(
        self,
        symptoms: list[dict[str, Any]],
        assessment_id: str | None = None,
        patient_drug_classes: list[str] | None = None,
        urgency_factors: dict[str, UrgencyFactor] | None = None,
        llm_confidence: float | None = None,
        llm_samples: list[dict] | None = None,
    ) -> DecisionResult:
        """
        执行完整决策流程。

        Args:
            symptoms: 感知层输出的结构化症状列表
            assessment_id: 评估ID
            patient_drug_classes: 患者用药类别
            urgency_factors: 各症状紧迫因子
            llm_confidence: LLM 自评置信度
            llm_samples: LLM 多次采样结果

        Returns:
            DecisionResult 完整决策结果
        """
        audit = AuditTrailBuilder(engine_version=self._engine_version)
        snapshot_hash = ""
        if self._rule_engine:
            snapshot_hash = self._rule_engine.get_snapshot_hash()
        audit.start(assessment_id, snapshot_hash)

        # ---- Step 1: 规则引擎评估 ----
        t0 = time.monotonic()
        matched_rules = self._evaluate_rules(symptoms, snapshot_hash)
        t1 = time.monotonic()

        audit.record_custom_step(
            step_name="规则引擎评估",
            input_data={"symptom_count": len(symptoms)},
            output_data={"matched_count": len(matched_rules)},
            duration_ms=(t1 - t0) * 1000,
            notes=f"规则引擎返回{len(matched_rules)}条命中规则",
        )

        # ---- Step 2: CTCAE 分级 ----
        t0 = time.monotonic()
        grades = self._grade_symptoms(symptoms, matched_rules)
        t1 = time.monotonic()

        all_rule_ids = [r.get("rule_id", "") for r in matched_rules]
        audit.record_grading(
            input_symptoms=symptoms,
            grades=grades,
            rules_evaluated=all_rule_ids,
            duration_ms=(t1 - t0) * 1000,
        )

        # ---- Step 3: 综合风险评分 ----
        t0 = time.monotonic()
        risk_score = self._scorer.compute_risk_score(
            grades, urgency_factors, patient_drug_classes,
        )
        t1 = time.monotonic()
        audit.record_scoring(risk_score, (t1 - t0) * 1000)

        # ---- Step 4: 冲突解决 ----
        t0 = time.monotonic()
        resolution = self._resolver.resolve(
            matched_rules, patient_drug_classes,
        )
        t1 = time.monotonic()
        audit.record_conflict_resolution(resolution, (t1 - t0) * 1000)

        # ---- Step 5: 置信度计算 ----
        t0 = time.monotonic()
        confidence = self._confidence.compute(
            resolution.all_hits, llm_confidence, llm_samples,
        )
        t1 = time.monotonic()
        audit.record_confidence(confidence, (t1 - t0) * 1000)

        # ---- Step 6: 构建审计链 ----
        trail = audit.build()

        # ---- Step 7: 组装最终结果 ----
        # 最终风险等级: 取评分和冲突解决中的最高值
        final_risk = max(
            risk_score.risk_level,
            resolution.final_risk_level,
            key=lambda r: {"low": 0, "medium": 1, "high": 2}[r.value],
        )
        final_urgency = max(
            risk_score.urgency,
            resolution.final_urgency,
            key=lambda u: {
                "self_monitor": 0,
                "contact_team_routine": 1,
                "contact_team_24h": 2,
                "emergency_immediate": 3,
            }[u.value],
        )

        ctcae_grades = {g.symptom_type: g.ctcae_grade for g in grades}
        rule_versions = {
            r.get("rule_id", ""): r.get("version", "0.0.0")
            for r in matched_rules
        }

        return DecisionResult(
            risk_level=final_risk,
            urgency=final_urgency,
            should_contact_team=resolution.should_contact_team,
            ctcae_grades=ctcae_grades,
            risk_score=risk_score,
            conflict_resolution=resolution,
            confidence=confidence,
            audit_trail=trail,
            symptom_grades=grades,
            primary_rule_id=resolution.primary_rule.rule_id,
            matched_rule_ids=[h.rule_id for h in resolution.all_hits],
            rule_versions=rule_versions,
            ai_enhanced=llm_confidence is not None,
            ai_degraded=llm_confidence is None,
        )

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _evaluate_rules(
        self,
        symptoms: list[dict[str, Any]],
        snapshot_hash: str,
    ) -> list[dict[str, Any]]:
        """调用规则引擎评估，降级时返回空列表"""
        if self._rule_engine is None:
            return []
        try:
            return self._rule_engine.evaluate(symptoms, snapshot_hash)
        except Exception:
            # 规则引擎异常 → 不降级，向上抛出
            raise

    def _grade_symptoms(
        self,
        symptoms: list[dict[str, Any]],
        matched_rules: list[dict[str, Any]],
    ) -> list[SymptomGrade]:
        """
        为每个症状匹配最佳规则并分级。
        """
        # 按症状类型索引命中规则
        rules_by_symptom: dict[str, list[dict[str, Any]]] = {}
        for r in matched_rules:
            st = r.get("ctcae_term", r.get("category", "unknown"))
            rules_by_symptom.setdefault(st, []).append(r)

        grades: list[SymptomGrade] = []
        for symptom in symptoms:
            st = symptom.get("symptom_type", symptom.get("name", "unknown"))
            candidates = rules_by_symptom.get(st, [])

            if candidates:
                # 取优先级最高的规则
                best = max(candidates, key=lambda r: r.get("priority", 0))
                grade = self._scorer.grade_single_symptom(st, symptom, best)
            else:
                grade = self._scorer.grade_single_symptom(st, symptom, None)

            grades.append(grade)

        return grades
