"""
Фабрика LLM-провайдеров.

Читает settings.llm_provider и возвращает нужную реализацию.
Кэшируется на процесс: провайдер держит httpx-клиент и OAuth-токен.
"""

from functools import lru_cache

from app.agent.llm.base import LLMProvider
from app.agent.llm.gigachat import GigaChatLLM
from app.agent.llm.mock import MockLLM
from app.agent.llm.openrouter import OpenRouterLLM
from app.config import get_settings


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    """Возвращает LLM-провайдер по настройкам."""
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockLLM()

    if settings.llm_provider == "openrouter":
        return OpenRouterLLM()

    if settings.llm_provider == "gigachat":
        return GigaChatLLM()

    raise ValueError(f"Неизвестный провайдер: {settings.llm_provider}")
