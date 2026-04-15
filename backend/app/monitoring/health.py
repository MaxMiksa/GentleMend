"""
浅愈(GentleMend) — 健康检查端点

探针设计:
  GET /api/health       — 存活探针 (liveness)
    仅检查进程是否存活，不依赖外部服务。
    Kubernetes 用此判断是否需要重启容器。

  GET /api/health/ready — 就绪探针 (readiness)
    检查所有依赖服务连通性:
      - PostgreSQL: 执行 SELECT 1
      - Redis: 执行 PING
      - AI API: 可选，降级不影响就绪状态
    Kubernetes 用此判断是否可以接收流量。

  GET /api/metrics      — 指标导出 (内部)
    导出 MetricsCollector 快照，供监控系统拉取。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ComponentStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # 可用但有问题 (如 AI 降级)
    UNHEALTHY = "unhealthy"


class ComponentCheck(BaseModel):
    name: str
    status: ComponentStatus
    latency_ms: float = 0.0
    message: str = ""
    required: bool = True  # 是否影响整体就绪状态


class HealthResponse(BaseModel):
    status: ComponentStatus
    version: str
    timestamp: str
    uptime_seconds: float
    checks: list[ComponentCheck] = Field(default_factory=list)


# 应用启动时间
_start_time = time.time()
APP_VERSION = "0.1.0"


async def check_postgres(db_session_factory: Any) -> ComponentCheck:
    """PostgreSQL 连通性检查 — 执行 SELECT 1"""
    start = time.monotonic()
    try:
        async with db_session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
            result.scalar()
        elapsed = (time.monotonic() - start) * 1000
        return ComponentCheck(
            name="postgresql",
            status=ComponentStatus.HEALTHY,
            latency_ms=round(elapsed, 2),
            message="连接正常",
            required=True,
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentCheck(
            name="postgresql",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(elapsed, 2),
            message=f"连接失败: {type(e).__name__}: {e}",
            required=True,
        )


async def check_redis(redis_client: Any) -> ComponentCheck:
    """Redis 连通性检查 — 执行 PING"""
    start = time.monotonic()
    try:
        pong = await redis_client.ping()
        elapsed = (time.monotonic() - start) * 1000
        if pong:
            return ComponentCheck(
                name="redis",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(elapsed, 2),
                message="PONG",
                required=True,
            )
        raise ConnectionError("PING 未返回 PONG")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentCheck(
            name="redis",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(elapsed, 2),
            message=f"连接失败: {type(e).__name__}: {e}",
            required=True,
        )


async def check_ai_api(ai_base_url: str | None = None) -> ComponentCheck:
    """
    AI API 连通性检查 — 可选组件

    AI 降级不影响系统就绪状态 (required=False)。
    规则引擎作为确定性底线，AI 不可用时系统仍可正常评估。
    """
    if not ai_base_url:
        return ComponentCheck(
            name="ai_api",
            status=ComponentStatus.DEGRADED,
            message="未配置 AI API 地址，使用纯规则引擎模式",
            required=False,
        )

    start = time.monotonic()
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ai_base_url}/health")
            elapsed = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return ComponentCheck(
                    name="ai_api",
                    status=ComponentStatus.HEALTHY,
                    latency_ms=round(elapsed, 2),
                    message="AI 服务可用",
                    required=False,
                )
            return ComponentCheck(
                name="ai_api",
                status=ComponentStatus.DEGRADED,
                latency_ms=round(elapsed, 2),
                message=f"AI 服务返回 {resp.status_code}",
                required=False,
            )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentCheck(
            name="ai_api",
            status=ComponentStatus.DEGRADED,
            latency_ms=round(elapsed, 2),
            message=f"AI 服务不可达: {type(e).__name__}",
            required=False,
        )


def liveness_check() -> HealthResponse:
    """
    GET /api/health — 存活探针

    仅检查进程存活，不依赖任何外部服务。
    返回 200 即表示进程正常运行。
    """
    return HealthResponse(
        status=ComponentStatus.HEALTHY,
        version=APP_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(time.time() - _start_time, 1),
    )


async def readiness_check(
    db_session_factory: Any,
    redis_client: Any,
    ai_base_url: str | None = None,
) -> HealthResponse:
    """
    GET /api/health/ready — 就绪探针

    并发检查所有依赖组件:
      - PostgreSQL (required) — 不可用则不就绪
      - Redis (required) — 不可用则不就绪
      - AI API (optional) — 不可用仅标记降级
    """
    import asyncio

    checks = await asyncio.gather(
        check_postgres(db_session_factory),
        check_redis(redis_client),
        check_ai_api(ai_base_url),
    )

    # 整体状态: 任何 required 组件 unhealthy -> 整体 unhealthy
    required_unhealthy = any(
        c.status == ComponentStatus.UNHEALTHY and c.required
        for c in checks
    )
    any_degraded = any(
        c.status == ComponentStatus.DEGRADED for c in checks
    )

    if required_unhealthy:
        overall = ComponentStatus.UNHEALTHY
    elif any_degraded:
        overall = ComponentStatus.DEGRADED
    else:
        overall = ComponentStatus.HEALTHY

    return HealthResponse(
        status=overall,
        version=APP_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(time.time() - _start_time, 1),
        checks=list(checks),
    )
