"""Тесты polling runner."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.telegram import runner


async def test_run_polling_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без TELEGRAM_BOT_TOKEN — понятная ошибка, не запуск с пустым токеном."""
    settings = runner.get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", "")

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        await runner.run_polling()


async def test_run_polling_deletes_webhook_then_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Перед polling снимаем webhook — иначе Telegram отдаёт 409."""
    settings = runner.get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")

    fake_bot = MagicMock()
    fake_bot.delete_webhook = AsyncMock()
    fake_bot.session = MagicMock()
    fake_bot.session.close = AsyncMock()

    fake_dispatcher = MagicMock()
    fake_dispatcher.start_polling = AsyncMock()

    monkeypatch.setattr(runner, "create_bot", lambda: fake_bot)
    monkeypatch.setattr(runner, "create_dispatcher", lambda: fake_dispatcher)
    monkeypatch.setattr(runner, "engine", MagicMock(dispose=AsyncMock()))

    await runner.run_polling()

    fake_bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
    fake_dispatcher.start_polling.assert_awaited_once_with(fake_bot)
    fake_bot.session.close.assert_awaited_once()
