"""
Протокол LLM-провайдера.
"""

from typing import Protocol


class LLMProvider(Protocol):
    """Контракт LLM-провайдера."""

    async def chat(self, system: str, user: str) -> str:
        """
        Отправляет system + user сообщение, возвращает текст ответа.
        """
        ...

    @property
    def name(self) -> str:
        """Имя провайдера для логов и записи в Message.llm_provider."""
        ...
