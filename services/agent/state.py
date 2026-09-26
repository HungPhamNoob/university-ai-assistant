# ============================================
# services/agent/state.py
# ============================================
"""
State schemas implementing the 'different-state' pattern.
Parent and Subgraphs have isolated schemas to prevent state leakage.
Context fields (user_id, email) are passed down for automatic tool injection.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class PrimaryState(TypedDict):
    """Parent graph state. Tracks routing, global history, and user context."""

    messages: Annotated[list[AnyMessage], add_messages]
    active_agent: str | None
    # Transparency metadata from the last context assembly of the turn
    # (memory injected / history trimmed / budgets) — surfaced over SSE.
    context_report: dict | None
    # user_id: Optional[str]
    # email: Optional[str]


class SubgraphState(TypedDict):
    """Subgraph state. Isolates iteration guards and inherits user context."""

    messages: Annotated[list[AnyMessage], add_messages]
    max_iterations: int
    current_iteration: int
    memory_context: dict | None
    # Latest ContextReport.to_dict() from this subgraph's agent node; the
    # parent lifts it into PrimaryState when the child returns.
    context_report: dict | None
    # user_id: Optional[str]
    # email: Optional[str]
