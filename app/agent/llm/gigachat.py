"""
GigaChat-провайдер LLM.
"""

import logging
from typing import Any

from langchain_gigachat.chat_models import GigaChat

from app.config import get_settings

logger = logging.getLogger(__name__)


class GigaChatLLM:
    """LLM-провайдер через GigaChat."""

    def __init__(
        self,
        credentials: str | None = None,
        model: str | None = None,
        scope: str | None = None,
        timeout: float = 30.0,
        verify_ssl: bool | None = None,
        client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._credentials = (
            credentials if credentials is not None else settings.gigachat_credentials
        )
        self._model = model if model is not None else settings.gigachat_model
        self._scope = scope if scope is not None else settings.gigachat_scope
        self._timeout = timeout
        # В проде verify_ssl=True (по умолчанию). В dev — из настроек.
        if verify_ssl is None:
            verify_ssl = settings.gigachat_verify_ssl
        self._verify_ssl = verify_ssl
        self._client = client

    @property
    def name(self) -> str:
        return "gigachat"

    def _build_client(self) -> GigaChat:
        """Создаёт клиент GigaChat через langchain-gigachat."""
        return GigaChat(
            credentials=self._credentials,
            model=self._model,
            scope=self._scope,
            verify_ssl_certs=self._verify_ssl,
            timeout=self._timeout,
        )

    async def chat(self, system: str, user: str) -> str:
        """Отправляет system + user, возвращает текст ответа."""
        client = self._client or self._build_client()

        messages = [
            ("system", system),
            ("human", user),
        ]

        try:
            response = await client.ainvoke(messages)
        except Exception:
            logger.exception("gigachat chat failed")
            raise

        content = response.content
        return content if isinstance(content, str) else str(content)
