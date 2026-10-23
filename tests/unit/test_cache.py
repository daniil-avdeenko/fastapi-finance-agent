"""Тесты lifecycle Redis-клиента (app/cache.py)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from app import cache


@pytest.fixture(autouse=True)
def reset_cache_state(monkeypatch):
    """
    Сбрасывает глобальное состояние app.cache между тестами.
    """
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_client_unavailable", False)
    yield
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_client_unavailable", False)


@pytest.fixture
def fake_redis(monkeypatch):
    """
    Фейковый async-клиент Redis, перехватывающий from_url.

    Возвращает (client, captured), где captured — словарь с url и kwargs,
    с которыми был вызван from_url.
    """
    client = MagicMock()
    client.ping = AsyncMock()
    client.aclose = AsyncMock()

    captured: dict[str, object] = {}

    def fake_from_url(url: str, **kwargs: object) -> MagicMock:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return client

    monkeypatch.setattr(cache.aioredis, "from_url", fake_from_url)
    return client, captured


@pytest.fixture
def patch_redis_url(monkeypatch):
    """
    Патчит cache.get_settings — возвращает объект с заданным redis_url.
    """

    def _patch(url: str) -> None:
        monkeypatch.setattr(
            cache,
            "get_settings",
            lambda: SimpleNamespace(redis_url=url),
        )

    return _patch


async def test_get_cache_returns_client(fake_redis) -> None:
    """При успешном подключении get_cache возвращает клиент."""
    client, _ = fake_redis

    result = await cache.get_cache()

    assert result is client


async def test_get_cache_passes_socket_timeouts(fake_redis, patch_redis_url) -> None:
    """
    get_cache передаёт в from_url явные socket_timeout и socket_connect_timeout.
    """
    patch_redis_url("redis://test-host:6380/0")
    _, captured = fake_redis

    await cache.get_cache()

    assert captured["url"] == "redis://test-host:6380/0"
    assert captured["kwargs"]["socket_timeout"] == 1
    assert captured["kwargs"]["socket_connect_timeout"] == 1
    assert captured["kwargs"]["decode_responses"] is True


async def test_get_cache_uses_default_url_when_empty(fake_redis, patch_redis_url) -> None:
    """Пустой redis_url в настройках — fallback на redis://localhost:6379/0."""
    patch_redis_url("")
    _, captured = fake_redis

    await cache.get_cache()

    assert captured["url"] == "redis://localhost:6379/0"


async def test_get_cache_caches_client(fake_redis) -> None:
    """Повторный вызов возвращает тот же клиент — не пересоздаёт соединение."""
    client, _ = fake_redis

    first = await cache.get_cache()
    second = await cache.get_cache()

    assert first is second


async def test_get_cache_marks_unavailable_on_error(monkeypatch) -> None:
    """RedisError при подключении — возвращает None и ставит _client_unavailable."""

    def raising_from_url(*args, **kwargs):
        raise RedisError("connection refused")

    monkeypatch.setattr(cache.aioredis, "from_url", raising_from_url)

    result = await cache.get_cache()

    assert result is None
    assert cache._client_unavailable is True


async def test_get_cache_does_not_retry_after_failure(monkeypatch) -> None:
    """
    После первого провала get_cache возвращает None без повторной попытки.
    """
    call_count = {"n": 0}

    def counting_from_url(*args, **kwargs):
        call_count["n"] += 1
        raise RedisError("down")

    monkeypatch.setattr(cache.aioredis, "from_url", counting_from_url)

    await cache.get_cache()
    await cache.get_cache()
    await cache.get_cache()

    assert call_count["n"] == 1
    assert cache._client_unavailable is True


async def test_close_cache_closes_connection(fake_redis) -> None:
    """close_cache закрывает соединение и обнуляет _client."""
    client, _ = fake_redis
    await cache.get_cache()

    await cache.close_cache()

    client.aclose.assert_awaited_once()
    assert cache._client is None


async def test_close_cache_safe_when_not_initialized() -> None:
    """close_cache без инициализированного клиента не падает."""
    await cache.close_cache()

    assert cache._client is None
