"""
浅愈(GentleMend) — 执行层 (Execution Layer)

职责：基于决策层输出，生成患者/医生可读的建议，
触发协同请求，创建不可变评估快照。

核心组件:
  - AdviceGenerator: 建议生成管线
  - CollaborationTrigger: 协同请求触发机制
  - SnapshotBuilder: 不可变快照生成
  - ExecutionEngine: 执行层总编排
"""

from app.execution.schemas import (
    AdviceItem,
    AdviceBundle,
    CollaborationRequest,
    NotificationChannel,
    AssessmentSnapshot,
)
from app.execution.advice_generator import AdviceGenerator
from app.execution.collaboration import CollaborationTrigger
from app.execution.snapshot import SnapshotBuilder
from app.execution.engine import ExecutionEngine

__all__ = [
    "AdviceItem",
    "AdviceBundle",
    "CollaborationRequest",
    "NotificationChannel",
    "AssessmentSnapshot",
    "AdviceGenerator",
    "CollaborationTrigger",
    "SnapshotBuilder",
    "ExecutionEngine",
]
