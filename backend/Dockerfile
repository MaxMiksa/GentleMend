# ============================================================
# 浅愈(GentleMend) Backend — 多阶段构建
# 基础镜像: Python 3.11 slim (体积小、安全补丁及时)
# ============================================================

# ---- Stage 1: 依赖安装 ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 系统依赖 (asyncpg 需要 libpq)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: 运行时 ----
FROM python:3.11-slim AS runtime

# 安全: 非 root 用户运行
RUN groupadd -r gentlemend && useradd -r -g gentlemend gentlemend

# 运行时依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 wget && \
    rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的依赖
COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

# 权限
RUN chown -R gentlemend:gentlemend /app
USER gentlemend

# 健康检查
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

# uvicorn 启动，开发模式支持热重载
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/app"]
