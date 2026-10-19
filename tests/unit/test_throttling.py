"""Тесты rate limit middleware с Redis и in-memory fallback."""

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from aiogram.types import Message

from app.telegram.middlewares import throttling


def make_message(user_id: int = 1) -> Message:
    """Фейковый Message с нужными полями."""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(id=user_id)
    message.answer = AsyncMock()
    return message


@pytest.fixture
async def fake_redis(monkeypatch):
    """fakeredis с поддержкой EVAL (extra [lua])."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_cache():
        return fake

    monkeypatch.setattr(throttling, "get_cache", _get_cache)
    yield fake
    await fake.aclose()


@pytest.fixture
async def no_redis(monkeypatch):
    """Redis недоступен — middleware должен уйти в fallback."""

    async def _get_cache():
        return None

    monkeypatch.setattr(throttling, "get_cache", _get_cache)


async def test_passes_under_limit_redis(fake_redis) -> None:
    middleware = throttling.ThrottlingMiddleware(max_requests=3, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    for _ in range(3):
        result = await middleware(handler, make_message(), {})

    assert handler.await_count == 3
    assert result == "ok"


async def test_blocks_over_limit_redis(fake_redis) -> None:
    middleware = throttling.ThrottlingMiddleware(max_requests=2, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(), {})
    await middleware(handler, make_message(), {})

    blocked = make_message()
    result = await middleware(handler, blocked, {})

    assert result is None
    assert handler.await_count == 2
    blocked.answer.assert_awaited_once()
    assert "Слишком много" in blocked.answer.call_args[0][0]


async def test_separate_limits_per_user_redis(fake_redis) -> None:
    middleware = throttling.ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(user_id=1), {})
    await middleware(handler, make_message(user_id=2), {})

    assert handler.await_count == 2


async def test_window_expires_redis(fake_redis, monkeypatch) -> None:
    """Запросы старше окна удаляются из sorted set — лимит сбрасывается."""
    middleware = throttling.ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    base_ns = 1_000_000_000_000_000_000
    monkeypatch.setattr(throttling.time, "time_ns", lambda: base_ns)

    await middleware(handler, make_message(), {})
    assert handler.await_count == 1

    # Второй в том же окне — блок
    result = await middleware(handler, make_message(), {})
    assert result is None
    assert handler.await_count == 1

    # +61 секунда — окно истекло
    monkeypatch.setattr(throttling.time, "time_ns", lambda: base_ns + 61_000_000_000)
    result = await middleware(handler, make_message(), {})
    assert result == "ok"
    assert handler.await_count == 2


async def test_fallback_when_redis_unavailable(no_redis) -> None:
    """Без Redis работает in-memory sliding window."""
    middleware = throttling.ThrottlingMiddleware(max_requests=2, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    await middleware(handler, make_message(), {})
    await middleware(handler, make_message(), {})

    blocked = make_message()
    result = await middleware(handler, blocked, {})

    assert result is None
    assert handler.await_count == 2
    blocked.answer.assert_awaited_once()


async def test_non_message_event_passes_through(fake_redis) -> None:
    """События, не являющиеся Message, middleware не трогает."""
    middleware = throttling.ThrottlingMiddleware(max_requests=1, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    other_event = MagicMock()

    result = await middleware(handler, other_event, {})

    assert result == "ok"
    assert handler.await_count == 1


async def test_redis_failure_falls_back_to_memory(fake_redis, monkeypatch) -> None:
    """При ошибке Redis в рантайме middleware не падает, а уходит в fallback."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    middleware = throttling.ThrottlingMiddleware(max_requests=2, window_seconds=60)
    handler = AsyncMock(return_value="ok")

    # Первый вызов — регистрация скрипта через рабочий fakeredis
    await middleware(handler, make_message(), {})

    # «Ломаем» скрипт после регистрации
    async def _broken_script(*args, **kwargs):
        raise RedisConnectionError("redis is dead")

    monkeypatch.setattr(middleware, "_script", _broken_script)

    # Второй вызов — падение скрипта, fallback на память
    result = await middleware(handler, make_message(), {})
    assert result == "ok"
    assert handler.await_count == 2
