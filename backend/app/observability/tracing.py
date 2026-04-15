"""
浅愈(GentleMend) — OpenTelemetry 集成

功能:
  - Trace 配置（关键路径 span）
  - 自定义 span: LLM 调用、规则引擎执行、数据库写入
  - Metrics: 请求延迟、AI 调用成功率、规则命中分布
  - MVP 阶段: 输出到控制台/日志文件
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

SERVICE_NAME = "gentlemend-backend"
SERVICE_VERSION = "0.1.0"


# ============================================================
# 初始化
# ============================================================

def init_telemetry(
    otlp_endpoint: str | None = None,
    use_console: bool = True,
) -> None:
    """
    初始化 OpenTelemetry Traces + Metrics。

    Args:
        otlp_endpoint: OTLP gRPC 端点。None 时仅输出到控制台。
        use_console: MVP 阶段输出到控制台/日志文件。
    """
    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": SERVICE_VERSION,
    })

    # --- Traces ---
    tracer_provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=otlp_endpoint),
            ),
        )
    if use_console:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter()),
        )

    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    readers = []
    if otlp_endpoint:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=otlp_endpoint),
                export_interval_millis=10_000,
            ),
        )
    if use_console:
        readers.append(
            PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=30_000,
            ),
        )

    meter_provider = MeterProvider(
        resource=resource, metric_readers=readers,
    )
    metrics.set_meter_provider(meter_provider)


# ============================================================
# Tracer / Meter 获取
# ============================================================

def get_tracer(name: str = SERVICE_NAME) -> trace.Tracer:
    return trace.get_tracer(name, SERVICE_VERSION)


def get_meter(name: str = SERVICE_NAME) -> metrics.Meter:
    return metrics.get_meter(name, SERVICE_VERSION)


# ============================================================
# 预定义 Metrics
# ============================================================

_meter = get_meter()

# 请求延迟直方图
request_duration = _meter.create_histogram(
    name="gentlemend.http.request.duration",
    description="HTTP 请求延迟（毫秒）",
    unit="ms",
)

# AI 调用计数器
ai_call_counter = _meter.create_counter(
    name="gentlemend.ai.calls.total",
    description="AI/LLM 调用总次数",
)

ai_call_errors = _meter.create_counter(
    name="gentlemend.ai.calls.errors",
    description="AI/LLM 调用失败次数",
)

# 规则命中分布
rule_hit_counter = _meter.create_counter(
    name="gentlemend.rules.hits.total",
    description="规则命中次数（按 rule_id 分组）",
)

# 评估处理延迟
assessment_duration = _meter.create_histogram(
    name="gentlemend.assessment.duration",
    description="评估处理总延迟（毫秒）",
    unit="ms",
)


# ============================================================
# 自定义 Span 上下文管理器
# ============================================================

@contextmanager
def span_llm_call(
    model: str,
    prompt_version: str,
    input_tokens: int = 0,
) -> Generator[trace.Span, None, None]:
    """LLM 调用 span"""
    tracer = get_tracer()
    with tracer.start_as_current_span("llm.call") as span:
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.prompt_version", prompt_version)
        span.set_attribute("llm.input_tokens", input_tokens)
        ai_call_counter.add(1, {"model": model})
        start = time.monotonic()
        try:
            yield span
        except Exception as exc:
            span.set_status(
                trace.StatusCode.ERROR, str(exc),
            )
            ai_call_errors.add(1, {"model": model})
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            span.set_attribute("llm.duration_ms", duration_ms)


@contextmanager
def span_rule_engine(
    rule_count: int,
    snapshot_hash: str = "",
) -> Generator[trace.Span, None, None]:
    """规则引擎执行 span"""
    tracer = get_tracer()
    with tracer.start_as_current_span("rule_engine.execute") as span:
        span.set_attribute("rules.count", rule_count)
        span.set_attribute("rules.snapshot_hash", snapshot_hash)
        yield span


@contextmanager
def span_db_write(
    table: str,
    operation: str = "insert",
) -> Generator[trace.Span, None, None]:
    """数据库写入 span"""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"db.{operation}") as span:
        span.set_attribute("db.table", table)
        span.set_attribute("db.operation", operation)
        start = time.monotonic()
        try:
            yield span
        except Exception as exc:
            span.set_status(
                trace.StatusCode.ERROR, str(exc),
            )
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            span.set_attribute("db.duration_ms", duration_ms)


# ============================================================
# 装饰器：自动为函数创建 span
# ============================================================

def traced(
    span_name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable:
    """
    装饰器：自动为同步/异步函数创建 span。

    用法:
        @traced("assessment.process")
        async def process_assessment(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def record_rule_hits(rule_ids: list[str]) -> None:
    """记录规则命中到 metrics"""
    for rid in rule_ids:
        rule_hit_counter.add(1, {"rule_id": rid})
