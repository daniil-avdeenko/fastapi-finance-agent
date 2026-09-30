"""
Состояние графа агента.

Передаётся между узлами. Узлы возвращают dict с обновлениями —
LangGraph мерджит их в общий state.
"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Общее состояние агента на один запрос."""

    # Входные данные
    question: str  # вопрос пользователя
    chat_id: int  # Telegram chat_id (для контекста истории)

    # Заполняется узлом understand
    intent: (
        str  # 'summary' | 'projects' | 'project_detail' | 'transactions' | 'currencies' | 'unknown'
    )
    params: dict[str, Any]  # параметры для tool (даты, id, фильтры)

    # Заполняется узлом query_data
    data: Any  # результат tool (dict / list)
    error: str | None  # текст ошибки, если tool упал

    # Заполняется узлом format_answer
    answer: str  # финальный ответ для пользователя

    # Метаданные
    latency_ms: int | None  # сколько заняла обработка
