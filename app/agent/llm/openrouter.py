"""
OpenRouter-провайдер LLM.
"""

from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLLM:
    """LLM-провайдер через OpenRouter."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self._model = model if model is not None else settings.llm_model
        self._timeout = timeout
        self._client = client

    @property
    def name(self) -> str:
        return "openrouter"

    def _build_client(self) -> AsyncOpenAI:
        """Создаёт AsyncOpenAI-клиент. Отдельный метод — для тестируемости."""
        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=self._timeout,
        )

    async def chat(self, system: str, user: str) -> str:
        """Отправляет system + user, возвращает текст ответа."""
        client = self._client if self._client is not None else self._build_client()

        response = await client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        content: str | None = response.choices[0].message.content
        return content or ""
