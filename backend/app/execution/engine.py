"""
执行引擎 — 执行层总编排

编排流程:
  1. 接收决策层输出 (DecisionResult)
  2. 生成建议 (AdviceBundle)
  3. 判断并触发协同请求
  4. 构建不可变快照
  5. 输出 ExecutionResult
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.decision.schemas import DecisionResult
from app.execution.advice_generator import AdviceGenerator
from app.execution.collaboration import CollaborationTrigger
from app.execution.schemas import (
    AdviceBundle,
    AssessmentSnapshot,
    CollaborationRequest,
)
from app.execution.snapshot import SnapshotBuilder


class ExecutionResult(BaseModel):
    """执行层最终输出"""
    snapshot: AssessmentSnapshot
    advice_bundle: AdviceBundle
    collaboration_request: CollaborationRequest | None = None
    integrity_verified: bool = Field(
        default=True, description="快照完整性校验结果",
    )


class ExecutionEngine:
    """
    执行层总编排引擎

    协调 AdviceGenerator、CollaborationTrigger、SnapshotBuilder
    完成从 DecisionResult 到最终可持久化输出的完整流程。
    """

    def __init__(
        self,
        advice_generator: AdviceGenerator | None = None,
        collaboration_trigger: CollaborationTrigger | None = None,
        snapshot_builder: SnapshotBuilder | None = None,
        engine_version: str = "0.1.0",
    ):
        self._advice_gen = advice_generator or AdviceGenerator()
        self._collab = collaboration_trigger or CollaborationTrigger()
        self._snapshot = snapshot_builder or SnapshotBuilder(engine_version)
        self._engine_version = engine_version

    def execute(
        self,
        decision: DecisionResult,
        assessment_id: str,
        patient_id: str,
        original_description: str,
        symptoms_structured: list[dict[str, Any]],
        version: int = 1,
        ai_model_version: str | None = None,
        ai_prompt_version: str | None = None,
    ) -> ExecutionResult:
        """
        执行完整的执行层流程。

        Args:
            decision: 决策层输出
            assessment_id: 评估ID
            patient_id: 患者ID
            original_description: 患者原始描述
            symptoms_structured: 结构化症状
            version: 快照版本号
            ai_model_version: AI 模型版本
            ai_prompt_version: AI Prompt 版本

        Returns:
            ExecutionResult 包含快照、建议、协同请求
        """
        # Step 1: 生成建议
        advice_bundle = self._advice_gen.generate(decision)

        # Step 2: 判断是否触发协同请求
        collab_request = self._collab.auto_trigger(
            decision, assessment_id, patient_id,
        )

        # Step 3: 构建不可变快照
        snapshot = self._snapshot.build(
            assessment_id=assessment_id,
            original_description=original_description,
            symptoms_structured=symptoms_structured,
            decision=decision,
            advice_bundle=advice_bundle,
            version=version,
            ai_model_version=ai_model_version,
            ai_prompt_version=ai_prompt_version,
        )

        # Step 4: 验证快照完整性
        verified = SnapshotBuilder.verify_integrity(snapshot)

        return ExecutionResult(
            snapshot=snapshot,
            advice_bundle=advice_bundle,
            collaboration_request=collab_request,
            integrity_verified=verified,
        )
