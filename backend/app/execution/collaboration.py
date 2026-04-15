"""
协同请求触发机制 — 执行层核心组件

触发条件:
  - 自动触发: HighRiskDetected 领域事件
  - 手动触发: 用户点击"联系团队"

通知渠道选择:
  - 紧急 → 电话 + 短信
  - 高优先级 → 短信 + APP推送
  - 常规 → APP推送

超时升级:
  - 24h 未响应 → 通知上级
  - 48h 未响应 → 升级为 CRITICAL
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from app.decision.schemas import (
    DecisionResult,
    RiskLevel,
    UrgencyLevel,
)
from app.execution.schemas import (
    AdviceUrgency,
    CollaborationRequest,
    CollaborationStatus,
    EscalationLevel,
    NotificationChannel,
    NotificationTarget,
)


# 通知渠道选择矩阵
_CHANNEL_MATRIX: dict[str, list[NotificationChannel]] = {
    "emergency": [
        NotificationChannel.PHONE_CALL,
        NotificationChannel.SMS,
    ],
    "high": [
        NotificationChannel.SMS,
        NotificationChannel.APP_PUSH,
    ],
    "normal": [
        NotificationChannel.APP_PUSH,
    ],
}

# 通知内容模板
_NOTIFICATION_TEMPLATES = {
    "emergency_patient": (
        "您的症状评估为紧急情况。我们已通知您的医疗团队，"
        "请保持电话畅通。如果症状加重，请立即拨打120。"
    ),
    "emergency_clinician": (
        "[紧急] 患者{patient_id}的副作用评估触发紧急警报。"
        "风险等级: HIGH | 主要症状: {symptoms} | "
        "CTCAE分级: {grades} | 请立即处理。"
    ),
    "high_patient": (
        "您的症状评估建议尽快联系医疗团队。"
        "我们已发送通知，团队将在24小时内与您联系。"
    ),
    "high_clinician": (
        "[高优先级] 患者{patient_id}的副作用评估需要关注。"
        "风险等级: {risk_level} | 症状: {symptoms} | "
        "请在24小时内回复。"
    ),
    "normal_patient": (
        "您的联系请求已发送给医疗团队，"
        "团队将在工作时间内回复您。"
    ),
    "normal_clinician": (
        "患者{patient_id}请求联系医疗团队。"
        "风险等级: {risk_level} | 症状: {symptoms}"
    ),
    "escalation_24h": (
        "[升级通知] 患者{patient_id}的协同请求已超过24小时未响应。"
        "原始风险等级: {risk_level} | 请上级医师关注。"
    ),
    "escalation_48h": (
        "[紧急升级] 患者{patient_id}的协同请求已超过48小时未响应。"
        "已升级为CRITICAL级别，请立即处理。"
    ),
}

# 超时配置
ESCALATION_TIMEOUT_24H = timedelta(hours=24)
ESCALATION_TIMEOUT_48H = timedelta(hours=48)


class CollaborationTrigger:
    """
    协同请求触发器

    职责:
      1. 根据决策结果判断是否需要自动触发协同
      2. 选择通知渠道
      3. 生成通知内容
      4. 管理超时升级
    """

    def __init__(self, event_bus: Any = None):
        """
        Args:
            event_bus: 领域事件总线（用于发布 HighRiskDetected 等事件）
        """
        self._event_bus = event_bus

    # ----------------------------------------------------------
    # 自动触发
    # ----------------------------------------------------------

    def auto_trigger(
        self,
        decision: DecisionResult,
        assessment_id: str,
        patient_id: str,
    ) -> CollaborationRequest | None:
        """
        根据决策结果自动判断是否触发协同请求。

        触发条件:
          - risk_level == HIGH
          - urgency in (CONTACT_24H, EMERGENCY)
          - should_contact_team == True

        Returns:
            CollaborationRequest 或 None（不需要触发时）
        """
        if not decision.should_contact_team:
            return None

        priority = self._determine_priority(decision)
        channels = _CHANNEL_MATRIX.get(priority, _CHANNEL_MATRIX["normal"])

        symptoms_str = ", ".join(decision.ctcae_grades.keys())
        grades_str = ", ".join(
            f"{k}=G{v}" for k, v in decision.ctcae_grades.items()
        )

        # 选择模板
        patient_msg = _NOTIFICATION_TEMPLATES.get(
            f"{priority}_patient", _NOTIFICATION_TEMPLATES["normal_patient"],
        )
        clinician_tpl = _NOTIFICATION_TEMPLATES.get(
            f"{priority}_clinician", _NOTIFICATION_TEMPLATES["normal_clinician"],
        )
        clinician_msg = clinician_tpl.format(
            patient_id=patient_id,
            risk_level=decision.risk_level.value.upper(),
            symptoms=symptoms_str,
            grades=grades_str,
        )

        urgency_map = {
            "emergency": AdviceUrgency.HIGH,
            "high": AdviceUrgency.HIGH,
            "normal": AdviceUrgency.MEDIUM,
        }

        request = CollaborationRequest(
            assessment_id=assessment_id,
            patient_id=patient_id,
            trigger_type="auto",
            trigger_event="HighRiskDetected",
            urgency=urgency_map.get(priority, AdviceUrgency.MEDIUM),
            notification=NotificationTarget(
                channels=channels,
                reason=f"自动触发: 风险等级={decision.risk_level.value}",
                priority=priority,
            ),
            message_patient=patient_msg,
            message_clinician=clinician_msg,
        )

        # 发布领域事件
        if self._event_bus:
            self._event_bus.publish("HighRiskDetected", {
                "assessment_id": assessment_id,
                "patient_id": patient_id,
                "risk_level": decision.risk_level.value,
                "collaboration_request_id": request.request_id,
            })

        return request

    # ----------------------------------------------------------
    # 手动触发
    # ----------------------------------------------------------

    def manual_trigger(
        self,
        assessment_id: str,
        patient_id: str,
        patient_message: str = "",
        urgency: AdviceUrgency = AdviceUrgency.MEDIUM,
    ) -> CollaborationRequest:
        """
        用户手动点击"联系团队"时触发。
        """
        priority = "high" if urgency == AdviceUrgency.HIGH else "normal"
        channels = _CHANNEL_MATRIX.get(priority, _CHANNEL_MATRIX["normal"])

        return CollaborationRequest(
            assessment_id=assessment_id,
            patient_id=patient_id,
            trigger_type="manual",
            trigger_event="ContactTeamClicked",
            urgency=urgency,
            notification=NotificationTarget(
                channels=channels,
                reason="患者手动请求联系医疗团队",
                priority=priority,
            ),
            message_patient=_NOTIFICATION_TEMPLATES["normal_patient"],
            message_clinician=_NOTIFICATION_TEMPLATES["normal_clinician"].format(
                patient_id=patient_id,
                risk_level="N/A",
                symptoms=patient_message or "未提供",
            ),
        )

    # ----------------------------------------------------------
    # 超时升级
    # ----------------------------------------------------------

    def check_escalation(
        self, request: CollaborationRequest,
    ) -> CollaborationRequest:
        """
        检查协同请求是否需要超时升级。

        升级策略:
          - 24h 未响应 → ELEVATED，通知上级
          - 48h 未响应 → CRITICAL，紧急升级
        """
        if request.status != CollaborationStatus.PENDING:
            return request

        now = datetime.now(timezone.utc)
        elapsed = now - request.created_at

        if elapsed >= ESCALATION_TIMEOUT_48H:
            return request.model_copy(update={
                "escalation_level": EscalationLevel.CRITICAL,
                "escalated_at": now,
                "notification": NotificationTarget(
                    channels=[
                        NotificationChannel.PHONE_CALL,
                        NotificationChannel.SMS,
                    ],
                    reason="48小时未响应，紧急升级",
                    priority="emergency",
                ),
            })

        if elapsed >= ESCALATION_TIMEOUT_24H:
            return request.model_copy(update={
                "escalation_level": EscalationLevel.ELEVATED,
                "escalated_at": now,
                "notification": NotificationTarget(
                    channels=[
                        NotificationChannel.SMS,
                        NotificationChannel.APP_PUSH,
                    ],
                    reason="24小时未响应，升级通知上级",
                    priority="high",
                ),
            })

        return request

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    @staticmethod
    def _determine_priority(decision: DecisionResult) -> str:
        """根据决策结果确定通知优先级"""
        if decision.urgency == UrgencyLevel.EMERGENCY:
            return "emergency"
        if (
            decision.risk_level == RiskLevel.HIGH
            or decision.urgency == UrgencyLevel.CONTACT_24H
        ):
            return "high"
        return "normal"
