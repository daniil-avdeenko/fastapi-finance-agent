"""
Общие фикстуры для всех тестов.
"""

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci-only")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("MAIN_API_URL", "http://test.local")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")

import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from app.main import app

# ============================================================
#   FastAPI client (без БД)
# ============================================================


@pytest.fixture
async def client() -> AsyncClient:
    """Async HTTP-клиент для FastAPI без реального сервера."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ============================================================
#   PostgreSQL в контейнере (session-scoped)
# ============================================================


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    """
    Один Postgres-контейнер на всю сессию pytest.
    """
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


def _sync_run_migrations(sync_url: str) -> None:
    """Sync-прогон Alembic миграций (вызывается через to_thread)."""
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def db_engine(postgres_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    """
    Async engine, направленный на тестовый контейнер.
    """
    # testcontainers отдаёт psycopg2-URL — заменяем драйвер на asyncpg.
    raw_url = postgres_container.get_connection_url()
    async_url = raw_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

    # уводим Alembic в отдельный поток — не блокируем event loop тестов.
    await asyncio.to_thread(_sync_run_migrations, async_url)

    engine = create_async_engine(
        async_url,
        echo=False,
        poolclass=NullPool,  # каждое соединение в текущем loop'е, без переиспользования
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """
    Сессия с очисткой данных после теста.
    """
    from sqlalchemy import text

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
        # Чистим все таблицы, что создаёт Alembic
        await session.execute(text("TRUNCATE TABLE messages RESTART IDENTITY CASCADE"))
        await session.commit()
