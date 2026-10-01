"""
POST /telegram/webhook — точка входа Telegram-апдейтов.
"""

import logging

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """
    Принимает апдейт от Telegram и передаёт в aiogram dispatcher.
    """
    settings = get_settings()

    if not settings.telegram_webhook_secret:
        logger.error("TELEGRAM_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    provided_secret = request.headers.get(SECRET_HEADER)
    if provided_secret != settings.telegram_webhook_secret:
        logger.warning("Webhook rejected: invalid secret")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    bot = getattr(request.app.state, "bot", None)
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if bot is None or dispatcher is None:
        logger.error("Webhook called but bot/dispatcher not initialized")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    data = await request.json()
    update = Update.model_validate(data)

    await dispatcher.feed_update(bot, update)

    return {"ok": True}
