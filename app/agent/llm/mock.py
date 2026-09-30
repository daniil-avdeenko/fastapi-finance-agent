"""
MockLLM — провайдер для тестов и локальной разработки.
"""

from collections.abc import Callable, Iterable


class MockLLM:
    """
    Простой mock: список ответов или функция от (system, user).
    """

    def __init__(
        self,
        responses: Iterable[str] | None = None,
        handler: Callable[[str, str], str] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._handler = handler
        self._call_count = 0
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return "mock"

    async def chat(self, system: str, user: str) -> str:
        """Возвращает следующий ответ или вызывает handler."""
        self.calls.append((system, user))
        self._call_count += 1

        if self._handler is not None:
            return self._handler(system, user)

        if not self._responses:
            raise RuntimeError("MockLLM: нет заготовленных ответов")

        # Возвращаем ответы по порядку; если кончились — повторяем последний
        idx = min(self._call_count - 1, len(self._responses) - 1)
        return self._responses[idx]


# Проверка соответствия протоколу на уровне типов.
def _check_protocol() -> None:
    from app.agent.llm.base import LLMProvider

    _: LLMProvider = MockLLM()
