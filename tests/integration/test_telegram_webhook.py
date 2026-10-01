"""Тесты POST /telegram/webhook."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from httpx import AsyncClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def fake_bot() -> MagicMock:
    """Мок Bot — feed_update не ходит в сеть."""
    bot = MagicMock(spec=Bot)
    bot.id = 12345
    return bot


@pytest.fixture
def fake_dispatcher() -> MagicMock:
    dispatcher = MagicMock(spec=Dispatcher)
    dispatcher.feed_update = AsyncMock()
    return dispatcher


@pytest.fixture
def webhook_setup(
    monkeypatch: pytest.MonkeyPatch,
    fake_bot: MagicMock,
    fake_dispatcher: MagicMock,
) -> None:
    """Кладём моки в app.state и задаём секрет."""
    app.state.bot = fake_bot
    app.state.dispatcher = fake_dispatcher

    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_webhook_secret", "test-secret")


async def test_webhook_rejects_missing_secret(client: AsyncClient, webhook_setup: None) -> None:
    response = await client.post("/telegram/webhook", json={})

    assert response.status_code == 403


async def test_webhook_rejects_wrong_secret(client: AsyncClient, webhook_setup: None) -> None:
    response = await client.post(
        "/telegram/webhook",
        json={},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )

    assert response.status_code == 403


async def test_webhook_rejects_when_secret_not_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_bot: MagicMock,
    fake_dispatcher: MagicMock,
) -> None:
    app.state.bot = fake_bot
    app.state.dispatcher = fake_dispatcher
    monkeypatch.setattr(get_settings(), "telegram_webhook_secret", "")

    response = await client.post(
        "/telegram/webhook",
        json={},
        headers={"X-Telegram-Bot-Api-Secret-Token": "any"},
    )

    assert response.status_code == 503


async def test_webhook_feeds_update_to_dispatcher(
    client: AsyncClient,
    webhook_setup: None,
    fake_bot: MagicMock,
    fake_dispatcher: MagicMock,
) -> None:
    """Правильный секрет → update уходит в dispatcher.feed_update."""
    response = await client.post(
        "/telegram/webhook",
        json={
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "is_bot": False, "first_name": "T"},
                "text": "hi",
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    fake_dispatcher.feed_update.assert_awaited_once()

    call_args = fake_dispatcher.feed_update.call_args
    assert call_args.args[0] is fake_bot
    # Второй аргумент — распарсенный Update.
    assert call_args.args[1].update_id == 1


async def test_webhook_returns_503_when_state_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если lifespan не создал bot/dispatcher — 503, не 500."""
    monkeypatch.setattr(get_settings(), "telegram_webhook_secret", "test-secret")
    # Явно убираем state, если он был установлен предыдущими тестами.
    if hasattr(app.state, "bot"):
        del app.state.bot
    if hasattr(app.state, "dispatcher"):
        del app.state.dispatcher

    response = await client.post(
        "/telegram/webhook",
        json={},
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )

    assert response.status_code == 503
