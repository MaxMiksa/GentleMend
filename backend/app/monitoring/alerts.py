"""
浅愈(GentleMend) — 告警规则引擎

告警级别:
  P0 (Critical) — 立即处理: 系统不可用或数据安全风险
  P1 (Warning)  — 1小时内:  服务降级或性能异常
  P2 (Info)     — 工作日内: 需关注但不紧急

医疗场景特殊告警:
  - 高风险评估连续 N 次 → 可能是规则异常 (非真实患者群体突变)
  - AI 降级率 > 50%     → AI 服务可能故障
  - 审计日志 gap 检测   → 可能数据丢失 (医疗合规红线)
  - 评估完成率骤降      → 系统可能存在阻塞

告警渠道:
  P0 → 短信 + 电话 + Slack #oncall
  P1 → Slack #alerts + 邮件
  P2 → Slack #monitoring
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class AlertLevel(str, Enum):
    P0 = "P0"  # Critical — 立即处理
    P1 = "P1"  # Warning  — 1小时内
    P2 = "P2"  # Info     — 工作日内


class AlertChannel(str, Enum):
    SLACK = "slack"
    EMAIL = "email"
    SMS = "sms"
    PHONE = "phone"
    WEBHOOK = "webhook"


@dataclass
class Alert:
    level: AlertLevel
    rule_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    channels: list[AlertChannel] = field(default_factory=list)


# ============================================================
# 告警升级策略
# ============================================================

ESCALATION_POLICY: dict[AlertLevel, list[AlertChannel]] = {
    AlertLevel.P0: [
        AlertChannel.PHONE,
        AlertChannel.SMS,
        AlertChannel.SLACK,
        AlertChannel.EMAIL,
    ],
    AlertLevel.P1: [
        AlertChannel.SLACK,
        AlertChannel.EMAIL,
    ],
    AlertLevel.P2: [
        AlertChannel.SLACK,
    ],
}


# ============================================================
# 告警规则定义
# ============================================================

class AlertRuleEngine:
    """
    基于指标快照的告警规则评估器。

    每次评估接收 MetricsCollector.snapshot() 的输出，
    逐条检查规则，触发匹配的告警。
    """

    def __init__(self) -> None:
        self._rules: list[Callable[[dict[str, Any]], Alert | None]] = [
            self._rule_high_error_rate,
            self._rule_high_latency_p99,
            self._rule_ai_degradation,
            self._rule_assessment_completion_drop,
            self._rule_db_pool_exhaustion,
            self._rule_consecutive_high_risk,
            self._rule_audit_log_gap,
        ]
        # 状态追踪 (用于连续事件检测)
        self._consecutive_high_risk: int = 0
        self._last_audit_count: int | None = None

    def evaluate(self, snapshot: dict[str, Any]) -> list[Alert]:
        """评估所有规则，返回触发的告警列表"""
        alerts = []
        for rule_fn in self._rules:
            alert = rule_fn(snapshot)
            if alert:
                alert.channels = ESCALATION_POLICY.get(
                    alert.level, [AlertChannel.SLACK]
                )
                alerts.append(alert)
        return alerts

    # ---- P0: 5xx 错误率 > 5% ----
    def _rule_high_error_rate(self, snap: dict[str, Any]) -> Alert | None:
        errors = snap.get("red", {}).get("errors", {})
        rate = snap.get("red", {}).get("rate", {})
        total_requests = sum(rate.values()) if rate else 0
        total_5xx = sum(
            v for k, v in errors.items() if k.startswith("5xx")
        )
        if total_requests > 10 and total_5xx / total_requests > 0.05:
            return Alert(
                level=AlertLevel.P0,
                rule_name="high_error_rate",
                message=f"5xx 错误率 {total_5xx}/{total_requests} "
                        f"({total_5xx/total_requests:.1%}) 超过 5% 阈值",
                details={"5xx_count": total_5xx, "total": total_requests},
            )
        return None

    # ---- P1: P99 延迟 > 3000ms ----
    def _rule_high_latency_p99(self, snap: dict[str, Any]) -> Alert | None:
        duration = snap.get("red", {}).get("duration", {})
        for endpoint, stats in duration.items():
            if stats.get("p99_ms", 0) > 3000 and stats.get("samples", 0) > 10:
                return Alert(
                    level=AlertLevel.P1,
                    rule_name="high_latency_p99",
                    message=f"端点 {endpoint} P99 延迟 "
                            f"{stats['p99_ms']:.0f}ms 超过 3000ms 阈值",
                    details={"endpoint": endpoint, **stats},
                )
        return None

    # ---- P0: AI 降级率 > 50% ----
    def _rule_ai_degradation(self, snap: dict[str, Any]) -> Alert | None:
        ai = snap.get("business", {}).get("ai", {})
        rate = ai.get("degradation_rate", 0)
        total = ai.get("total_calls", 0)
        if total >= 5 and rate > 0.5:
            return Alert(
                level=AlertLevel.P0,
                rule_name="ai_degradation_critical",
                message=f"AI 降级率 {rate:.1%} 超过 50%，"
                        f"AI 服务可能故障，当前仅规则引擎兜底",
                details={"degradation_rate": rate, "total_calls": total},
            )
        return None

    # ---- P1: 评估完成率 < 80% ----
    def _rule_assessment_completion_drop(
        self, snap: dict[str, Any],
    ) -> Alert | None:
        assess = snap.get("business", {}).get("assessments", {})
        started = assess.get("started", 0)
        rate = assess.get("completion_rate", 1.0)
        if started >= 10 and rate < 0.8:
            return Alert(
                level=AlertLevel.P1,
                rule_name="assessment_completion_drop",
                message=f"评估完成率 {rate:.1%} 低于 80% 阈值，"
                        f"可能存在系统阻塞或超时",
                details={"completion_rate": rate, "started": started},
            )
        return None

    # ---- P0: 数据库连接池使用率 > 90% ----
    def _rule_db_pool_exhaustion(self, snap: dict[str, Any]) -> Alert | None:
        pool = snap.get("infrastructure", {}).get("db_pool", {})
        util = pool.get("utilization", 0)
        if util > 0.9:
            return Alert(
                level=AlertLevel.P0,
                rule_name="db_pool_exhaustion",
                message=f"PostgreSQL 连接池使用率 {util:.1%}，"
                        f"即将耗尽 ({pool.get('checked_out')}/{pool.get('size')})",
                details=pool,
            )
        return None

    # ---- P1: 连续 N 次高风险评估 (医疗特殊) ----
    def _rule_consecutive_high_risk(
        self, snap: dict[str, Any],
    ) -> Alert | None:
        risk = snap.get("business", {}).get("risk_distribution", {})
        high_count = risk.get("high", 0)
        # 简化: 检查高风险占比是否异常偏高
        total = sum(risk.values()) if risk else 0
        if total >= 20 and high_count / total > 0.6:
            return Alert(
                level=AlertLevel.P1,
                rule_name="consecutive_high_risk",
                message=f"高风险评估占比 {high_count/total:.1%} 异常偏高，"
                        f"请检查规则引擎是否存在误判",
                details={"high": high_count, "total": total},
            )
        return None

    # ---- P0: 审计日志 gap 检测 (医疗合规) ----
    def _rule_audit_log_gap(self, snap: dict[str, Any]) -> Alert | None:
        """
        审计日志完整性: 评估完成数应与审计记录数一致。
        如果评估已完成但审计日志缺失，可能存在数据丢失。
        这在医疗场景中是合规红线。

        注: 实际生产中应查询数据库比对，这里用指标近似检测。
        """
        assess = snap.get("business", {}).get("assessments", {})
        completed = assess.get("completed", 0)
        # 此规则需要外部注入审计计数，这里作为设计占位
        # 实际实现: SELECT count(*) FROM audit_logs WHERE action = 'assessment_completed'
        return None
