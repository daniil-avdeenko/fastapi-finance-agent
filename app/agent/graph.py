"""
Сборка LangGraph-графа агента.

Поток линейный:
    START → understand → query_data → format_answer → END

Граф stateless: LLM и tools берутся из фабрик внутри узлов, у самих узлов
состояния нет. Поэтому граф можно кэшировать на процесс.
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    format_answer_node,
    query_data_node,
    understand_node,
)
from app.agent.state import AgentState


def build_graph() -> Any:
    """Собирает и компилирует граф агента."""
    builder: StateGraph[AgentState] = StateGraph(AgentState)

    builder.add_node("understand", understand_node)
    builder.add_node("query_data", query_data_node)
    builder.add_node("format_answer", format_answer_node)

    builder.add_edge(START, "understand")
    builder.add_edge("understand", "query_data")
    builder.add_edge("query_data", "format_answer")
    builder.add_edge("format_answer", END)

    return builder.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Singleton скомпилированного графа (компиляция — не бесплатная)."""
    return build_graph()
