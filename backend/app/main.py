"""
浅愈(GentleMend) — FastAPI 应用入口
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv

# 加载项目根目录的 .env
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import engine, async_session, Base
from app.db.seed import seed_rules
from app.api.assessments import router as assessments_router
from app.api.contact_requests import router as contact_router
from app.api.events import router as events_router
from app.api.feedback import router as feedback_router
from app.api.patients import router as patients_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时建表（开发模式），关闭时清理连接"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        await seed_rules(session)
    yield
    await engine.dispose()


app = FastAPI(
    title="浅愈(GentleMend)",
    description="乳腺癌副作用智能评估系统 API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(assessments_router, prefix="/api/v1")
app.include_router(contact_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
