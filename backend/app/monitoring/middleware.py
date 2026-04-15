"""
浅愈(GentleMend) — FastAPI 监控中间件

自动采集 RED 指标:
  - 每个请求的 Rate / Error / Duration
  - 注入 X-Request-ID 头
  - 记录结构化访问日志
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.monitoring.metrics import ErrorCategory, metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    请求级指标采集中间件

    对每个 HTTP 请求自动记录:
      1. 请求计数 (Rate)
      2. 响应状态码分类 (Errors)
      3. 请求耗时 (Duration)
      4. 注入 X-Request-ID 用于链路追踪
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        # 注入请求 ID
        request_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4())[:8],
        )
        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            # 未捕获异常 → 500
            metrics.inc_error(ErrorCategory.SERVER_5XX, request.url.path)
            raise

        elapsed_ms = (time.monotonic() - start) * 1000

        # Rate
        metrics.inc_request(request.url.path, request.method)
        # Duration
        metrics.record_latency(request.url.path, elapsed_ms)
        # Errors
        if 400 <= response.status_code < 500:
            metrics.inc_error(ErrorCategory.CLIENT_4XX, request.url.path)
        elif response.status_code >= 500:
            metrics.inc_error(ErrorCategory.SERVER_5XX, request.url.path)

        # 响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

        return response
