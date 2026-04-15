"""
浅愈(GentleMend) — SQLAlchemy 2.0 async 基础配置
支持 PostgreSQL（生产）和 SQLite（本地开发）
"""
import os

from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# 优先使用 DATABASE_URL 环境变量，其次拼接 PG 参数，最后 fallback 到 SQLite
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DB_HOST = os.getenv("DB_HOST", "")
    if DB_HOST:
        DB_PORT = os.getenv("DB_PORT", "5432")
        DB_NAME = os.getenv("DB_NAME", "gentlemend")
        DB_USER = os.getenv("DB_USER", "gentlemend")
        DB_PASSWORD = os.getenv("DB_PASSWORD", "gentlemend_dev_2025")
        DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    else:
        # SQLite fallback（本地开发，无需 PostgreSQL）
        DATABASE_URL = "sqlite+aiosqlite:///./gentlemend_dev.db"

# SQLite 需要特殊配置
connect_args = {}
pool_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    pool_kwargs = {"pool_size": 5, "max_overflow": 0}
else:
    pool_kwargs = {"pool_size": 10, "max_overflow": 10}

engine = create_async_engine(
    DATABASE_URL, echo=False, connect_args=connect_args, **pool_kwargs,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


async def get_session():
    async with async_session() as session:
        yield session
