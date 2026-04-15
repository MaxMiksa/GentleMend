"""
浅愈(GentleMend) — structlog 结构化日志配置

功能:
  - JSON 格式输出（生产环境）/ 彩色控制台（开发环境）
  - 请求上下文自动注入（request_id, patient_id, assessment_id）
  - 敏感数据脱敏（患者姓名、症状描述截断）
  - 日志级别策略
  - 与 OpenTelemetry trace_id 关联
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

import structlog

# ============================================================
# 请求上下文 ContextVar
# ============================================================

_log_context: ContextVar[dict[str, Any]] = ContextVar(
    "_log_context", default={},
)


def bind_log_context(**kwargs: Any) -> None:
    """绑定请求级日志上下文（在中间件中调用）"""
    ctx = _log_context.get().copy()
    ctx.update(kwargs)
    _log_context.set(ctx)


def clear_log_context() -> None:
    """清除请求级日志上下文"""
    _log_context.set({})


# ============================================================
# 敏感数据脱敏处理器
# ============================================================

# 需要脱敏的字段名模式
_SENSITIVE_FIELDS = {
    "patient_name", "name", "phone", "id_card",
    "address", "email",
}
# 需要截断的长文本字段
_TRUNCATE_FIELDS = {
    "free_text_input", "symptoms_description", "ai_raw_output",
}
_TRUNCATE_MAX = 100


def _sanitize_value(key: str, value: Any) -> Any:
    """对单个字段值进行脱敏"""
    if key in _SENSITIVE_FIELDS and isinstance(value, str):
        if len(value) <= 1:
            return "*"
        return value[0] + "*" * (len(value) - 2) + value[-1]
    if key in _TRUNCATE_FIELDS and isinstance(value, str):
        if len(value) > _TRUNCATE_MAX:
            return value[:_TRUNCATE_MAX] + f"...[truncated, total={len(value)}]"
    return value


def sanitize_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog 处理器：敏感数据脱敏"""
    for key in list(event_dict.keys()):
        event_dict[key] = _sanitize_value(key, event_dict[key])
    return event_dict


# ============================================================
# 请求上下文注入处理器
# ============================================================

def inject_context_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """自动注入 ContextVar 中的请求上下文"""
    ctx = _log_context.get()
    for k, v in ctx.items():
        if k not in event_dict:
            event_dict[k] = v
    return event_dict


# ============================================================
# structlog 配置入口
# ============================================================

def configure_logging(
    env: str = "production",
    log_level: str = "INFO",
) -> None:
    """
    配置 structlog。

    日志级别策略:
      - DEBUG: 开发环境，含 SQL 查询、规则匹配细节
      - INFO:  生产环境默认，含请求/响应、评估流程关键节点
      - WARNING: 降级事件（AI 不可用回退规则引擎）
      - ERROR: 异常、数据库写入失败
      - CRITICAL: 审计链完整性校验失败

    Args:
        env: "development" | "production"
        log_level: 日志级别
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        inject_context_processor,
        sanitize_processor,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if env == "development":
        # 开发环境：彩色控制台输出
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                structlog.get_level_from_name(log_level),
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # 生产环境：JSON 格式输出
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(
                    ensure_ascii=False,
                ),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                structlog.get_level_from_name(log_level),
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """获取带模块名的 logger"""
    return structlog.get_logger(module=name)
