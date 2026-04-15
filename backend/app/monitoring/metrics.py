"""
浅愈(GentleMend) — 监控指标收集器

指标体系设计 (RED + 业务 + 基础设施):

┌─────────────────────────────────────────────────────────────────┐
│ 系统健康 (RED方法)                                              │
│  Rate:     请求速率 (按端点/方法)                                │
│  Errors:   错误率 (4xx / 5xx / AI超时 / 规则引擎异常)           │
│  Duration: 延迟分布 (P50 / P95 / P99)                           │
├─────────────────────────────────────────────────────────────────┤
│ 业务指标                                                        │
│  评估完成率 (started vs completed)                               │
│  风险等级分布 (low / medium / high)                              │
│  AI降级率 (fallback to rule-only)                               │
│  规则命中率 Top10                                                │
│  患者反馈满意度                                                  │
├─────────────────────────────────────────────────────────────────┤
│ 基础设施                                                        │
│  PostgreSQL 连接池使用率                                         │
│  Redis 命中率 / 内存使用                                         │
│  进程 CPU / 内存                                                 │
└─────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    CLIENT_4XX = "4xx"
    SERVER_5XX = "5xx"
    AI_TIMEOUT = "ai_timeout"
    AI_ERROR = "ai_error"
    RULE_ENGINE = "rule_engine"
    DB_ERROR = "db_error"
    VALIDATION = "validation"


@dataclass
class LatencyBucket:
    """延迟分位数统计 — 滑动窗口"""
    values: list[float] = field(default_factory=list)
    window_size: int = 1000  # 保留最近 N 个样本

    def record(self, duration_ms: float) -> None:
        self.values.append(duration_ms)
        if len(self.values) > self.window_size:
            self.values = self.values[-self.window_size:]

    def percentile(self, p: int) -> float:
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)


class MetricsCollector:
    """
    应用级指标收集器 — 单例模式

    轻量实现，不依赖 Prometheus/StatsD 等外部组件。
    笔试项目中展示指标设计思路，生产环境替换为 prometheus_client。
    """

    _instance: MetricsCollector | None = None

    def __new__(cls) -> MetricsCollector:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # ---- RED 指标 ----
        self.request_count: defaultdict[str, int] = defaultdict(int)
        self.error_count: defaultdict[str, int] = defaultdict(int)
        self.latency: defaultdict[str, LatencyBucket] = defaultdict(LatencyBucket)

        # ---- 业务指标 ----
        self.assessments_started: int = 0
        self.assessments_completed: int = 0
        self.assessments_failed: int = 0
        self.risk_distribution: defaultdict[str, int] = defaultdict(int)
        self.ai_calls_total: int = 0
        self.ai_degraded_total: int = 0
        self.rule_hits: defaultdict[str, int] = defaultdict(int)
        self.feedback_scores: list[float] = []

        # ---- 基础设施指标 (由探针更新) ----
        self.db_pool_size: int = 0
        self.db_pool_checked_out: int = 0
        self.redis_hit: int = 0
        self.redis_miss: int = 0

        self._start_time = time.time()

    # ---- RED: Rate ----
    def inc_request(self, endpoint: str, method: str = "GET") -> None:
        key = f"{method}:{endpoint}"
        self.request_count[key] += 1

    # ---- RED: Errors ----
    def inc_error(self, category: ErrorCategory, endpoint: str = "") -> None:
        self.error_count[category.value] += 1
        if endpoint:
            self.error_count[f"{category.value}:{endpoint}"] += 1

    # ---- RED: Duration ----
    def record_latency(self, endpoint: str, duration_ms: float) -> None:
        self.latency[endpoint].record(duration_ms)

    # ---- 业务: 评估 ----
    def on_assessment_started(self) -> None:
        self.assessments_started += 1

    def on_assessment_completed(self, risk_level: str) -> None:
        self.assessments_completed += 1
        self.risk_distribution[risk_level] += 1

    def on_assessment_failed(self) -> None:
        self.assessments_failed += 1

    # ---- 业务: AI ----
    def on_ai_call(self, degraded: bool = False) -> None:
        self.ai_calls_total += 1
        if degraded:
            self.ai_degraded_total += 1

    # ---- 业务: 规则 ----
    def on_rule_hit(self, rule_id: str) -> None:
        self.rule_hits[rule_id] += 1

    # ---- 业务: 反馈 ----
    def on_feedback(self, score: float) -> None:
        self.feedback_scores.append(score)

    # ---- 基础设施: 缓存 ----
    def on_cache_hit(self) -> None:
        self.redis_hit += 1

    def on_cache_miss(self) -> None:
        self.redis_miss += 1

    # ---- 快照: 导出当前指标 ----
    def snapshot(self) -> dict[str, Any]:
        """导出所有指标的当前快照，供 /metrics 端点使用"""
        uptime = time.time() - self._start_time

        # 规则命中 Top10
        top_rules = sorted(
            self.rule_hits.items(), key=lambda x: x[1], reverse=True,
        )[:10]

        # 延迟汇总
        latency_summary = {}
        for endpoint, bucket in self.latency.items():
            latency_summary[endpoint] = {
                "p50_ms": round(bucket.p50, 2),
                "p95_ms": round(bucket.p95, 2),
                "p99_ms": round(bucket.p99, 2),
                "samples": len(bucket.values),
            }

        # 评估完成率
        completion_rate = (
            self.assessments_completed / self.assessments_started
            if self.assessments_started > 0
            else 0.0
        )

        # AI 降级率
        ai_degradation_rate = (
            self.ai_degraded_total / self.ai_calls_total
            if self.ai_calls_total > 0
            else 0.0
        )

        # Redis 命中率
        cache_total = self.redis_hit + self.redis_miss
        cache_hit_rate = (
            self.redis_hit / cache_total if cache_total > 0 else 0.0
        )

        # 平均满意度
        avg_feedback = (
            sum(self.feedback_scores) / len(self.feedback_scores)
            if self.feedback_scores
            else None
        )

        return {
            "uptime_seconds": round(uptime, 1),
            "red": {
                "rate": dict(self.request_count),
                "errors": dict(self.error_count),
                "duration": latency_summary,
            },
            "business": {
                "assessments": {
                    "started": self.assessments_started,
                    "completed": self.assessments_completed,
                    "failed": self.assessments_failed,
                    "completion_rate": round(completion_rate, 4),
                },
                "risk_distribution": dict(self.risk_distribution),
                "ai": {
                    "total_calls": self.ai_calls_total,
                    "degraded": self.ai_degraded_total,
                    "degradation_rate": round(ai_degradation_rate, 4),
                },
                "rule_hits_top10": top_rules,
                "feedback_avg": avg_feedback,
            },
            "infrastructure": {
                "db_pool": {
                    "size": self.db_pool_size,
                    "checked_out": self.db_pool_checked_out,
                    "utilization": (
                        round(self.db_pool_checked_out / self.db_pool_size, 4)
                        if self.db_pool_size > 0
                        else 0.0
                    ),
                },
                "redis": {
                    "hit": self.redis_hit,
                    "miss": self.redis_miss,
                    "hit_rate": round(cache_hit_rate, 4),
                },
            },
        }


# 全局单例
metrics = MetricsCollector()
