"""
Фабрика LLM-провайдеров.

Читает settings.llm_provider и возвращает нужную реализацию.
В тестах и dev по умолчанию — MockLLM.
"""

from app.agent.llm.base import LLMProvider
from app.agent.llm.mock import MockLLM
from app.agent.llm.openrouter import OpenRouterLLM
from app.config import get_settings


def get_llm() -> LLMProvider:
    """
    Возвращает LLM-провайдер по настройкам.
    """
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockLLM()

    if settings.llm_provider == "openrouter":
        return OpenRouterLLM()

    raise ValueError(f"Неизвестный провайдер: {settings.llm_provider}")
