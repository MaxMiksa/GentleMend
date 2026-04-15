"""
浅愈(GentleMend) — 数据库连接与缓存配置
asyncpg + SQLAlchemy 2.0 async + Redis 缓存策略
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ============================================================
# 配置
# ============================================================

class DatabaseSettings(BaseSettings):
    """PostgreSQL 连接池配置 — asyncpg 驱动"""

    model_config = {"env_prefix": "DB_"}

    host: str = "localhost"
    port: int = 5432
    name: str = "gentlemend"
    user: str = "gentlemend_app"
    password: SecretStr = SecretStr("gentlemend_app_2025")

    # --- asyncpg 连接池参数 ---
    pool_size: int = Field(
        default=10,
        description="常驻连接数。医疗系统并发不高但要求低延迟，10 足够",
    )
    max_overflow: int = Field(
        default=10,
        description="突发连接数。高风险评估可能触发并发写入",
    )
    pool_timeout: int = Field(
        default=10,
        description="等待连接的超时秒数",
    )
    pool_recycle: int = Field(
        default=1800,
        description="连接回收周期(秒)。防止 PG 端超时断开",
    )
    pool_pre_ping: bool = Field(
        default=True,
        description="每次取连接前 ping 一下，避免用到已断开的连接",
    )
    echo: bool = Field(
        default=False,
        description="SQL 日志输出。开发环境可开启",
    )

    @property
    def async_url(self) -> str:
        pwd = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"

    # --- asyncpg 驱动级参数 (透传) ---
    statement_cache_size: int = Field(
        default=100,
        description="asyncpg prepared statement 缓存。医疗查询模式固定，缓存命中率高",
    )
    command_timeout: int = Field(
        default=30,
        description="单条 SQL 超时(秒)。防止慢查询拖垮连接池",
    )


class RedisSettings(BaseSettings):
    """Redis 缓存配置"""

    model_config = {"env_prefix": "REDIS_"}

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None

    # 缓存 TTL (秒)
    rule_snapshot_ttl: int = Field(
        default=0,
        description="规则快照缓存。0=不过期，通过版本变更主动失效",
    )
    patient_info_ttl: int = Field(
        default=300,
        description="患者基本信息缓存 5 分钟",
    )
    assessment_result_ttl: int = Field(
        default=3600,
        description="评估结果缓存 1 小时。不可变数据，可以长缓存",
    )

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


# ============================================================
# Engine & Session 工厂
# ============================================================

def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    """创建 SQLAlchemy async engine，配置 asyncpg 连接池"""
    if settings is None:
        settings = DatabaseSettings()

    return create_async_engine(
        settings.async_url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout,
        pool_recycle=settings.pool_recycle,
        pool_pre_ping=settings.pool_pre_ping,
        echo=settings.echo,
        # asyncpg 驱动级参数
        connect_args={
            "statement_cache_size": settings.statement_cache_size,
            "command_timeout": settings.command_timeout,
            # 医疗数据 — 强制 UTF-8
            "server_settings": {
                "application_name": "gentlemend-backend",
                "timezone": "Asia/Shanghai",
            },
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """创建 session 工厂，用于 FastAPI Depends 注入"""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,  # 避免 commit 后访问属性触发隐式查询
    )


@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """事务级 session 上下文管理器"""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ============================================================
# 缓存策略实现
# ============================================================

class CacheKeyBuilder:
    """
    缓存 key 命名规范:
      gentlemend:{domain}:{identifier}:{version?}

    缓存策略:
    ┌─────────────────────┬──────────┬────────────────────────────────┐
    │ 数据类型            │ TTL      │ 失效策略                       │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ 规则快照            │ 不过期   │ 版本变更时主动删除旧 key       │
    │ (copy-on-write)     │          │ key 含版本号，天然隔离         │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ 患者基本信息        │ 5 min    │ TTL 过期 + 更新时主动失效      │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ 评估结果            │ 1 hour   │ 不可变数据，无需失效策略       │
    │ (immutable)         │          │ TTL 仅控制内存占用             │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ 评估列表/分页       │ 不缓存   │ 实时查询，数据变化频繁         │
    ├─────────────────────┼──────────┼────────────────────────────────┤
    │ 健康检查            │ 不缓存   │ 必须实时反映系统状态           │
    └─────────────────────┴──────────┴────────────────────────────────┘
    """

    PREFIX = "gentlemend"

    @staticmethod
    def rule_snapshot(version_hash: str) -> str:
        """规则快照 key — 含版本 hash，天然支持 copy-on-write"""
        return f"{CacheKeyBuilder.PREFIX}:rules:snapshot:{version_hash}"

    @staticmethod
    def patient(patient_id: str) -> str:
        return f"{CacheKeyBuilder.PREFIX}:patient:{patient_id}"

    @staticmethod
    def assessment(assessment_id: str) -> str:
        return f"{CacheKeyBuilder.PREFIX}:assessment:{assessment_id}"

    @staticmethod
    def rule_version_active(rule_id: str) -> str:
        return f"{CacheKeyBuilder.PREFIX}:rule_version:active:{rule_id}"
