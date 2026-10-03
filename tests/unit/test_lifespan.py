"""
Тесты lifespan FastAPI: создание бота, установка webhook, shutdown.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.main import app, lifespan


def _clean_state() -> None:
    """Убирает bot/dispatcher из app.state между тестами."""
    for attr in ("bot", "dispatcher"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def fake_bot() -> MagicMock:
    """Bot с async-методами — set_webhook и session.close."""
    bot = MagicMock()
    bot.set_webhook = AsyncMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    return bot


@pytest.fixture
def fake_dispatcher() -> MagicMock:
    return MagicMock()


@pytest.fixture
def patch_bot_factories(
    monkeypatch: pytest.MonkeyPatch,
    fake_bot: MagicMock,
    fake_dispatcher: MagicMock,
) -> None:
    """Подменяет create_bot / create_dispatcher в модуле app.telegram.bot."""
    monkeypatch.setattr("app.telegram.bot.create_bot", lambda: fake_bot)
    monkeypatch.setattr("app.telegram.bot.create_dispatcher", lambda: fake_dispatcher)


async def test_lifespan_creates_bot_in_webhook_mode(
    monkeypatch: pytest.MonkeyPatch,
    patch_bot_factories: None,
    fake_bot: MagicMock,
    fake_dispatcher: MagicMock,
) -> None:
    """Webhook-режим + токен → bot/dispatcher в app.state."""
    _clean_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_webhook_url", "")

    async with lifespan(app):
        assert app.state.bot is fake_bot
        assert app.state.dispatcher is fake_dispatcher

    _clean_state()


async def test_lifespan_sets_webhook_when_url_provided(
    monkeypatch: pytest.MonkeyPatch,
    patch_bot_factories: None,
    fake_bot: MagicMock,
) -> None:
    """Если задан webhook_url — lifespan вызывает set_webhook."""
    _clean_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_webhook_url", "https://example.com/telegram/webhook")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "secret")

    async with lifespan(app):
        pass

    fake_bot.set_webhook.assert_awaited_once_with(
        url="https://example.com/telegram/webhook",
        secret_token="secret",
        drop_pending_updates=True,
    )
    _clean_state()


async def test_lifespan_skips_bot_in_polling_mode(
    monkeypatch: pytest.MonkeyPatch,
    patch_bot_factories: None,
) -> None:
    """Polling-режим → lifespan не создаёт бота (он живёт в runner.py)."""
    _clean_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_mode", "polling")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")

    async with lifespan(app):
        assert not hasattr(app.state, "bot")
        assert not hasattr(app.state, "dispatcher")


async def test_lifespan_skips_bot_without_token(
    monkeypatch: pytest.MonkeyPatch,
    patch_bot_factories: None,
) -> None:
    """Без токена lifespan не поднимает бота, даже в webhook-режиме."""
    _clean_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_bot_token", "")

    async with lifespan(app):
        assert not hasattr(app.state, "bot")


async def test_lifespan_closes_bot_session_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    patch_bot_factories: None,
    fake_bot: MagicMock,
) -> None:
    """Shutdown закрывает session бота — иначе утечка соединений."""
    _clean_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_webhook_url", "")

    async with lifespan(app):
        pass

    fake_bot.session.close.assert_awaited_once()
    _clean_state()
