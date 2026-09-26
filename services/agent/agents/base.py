# ============================================
# services/agent/agents/base.py (FIXED)
# ============================================
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from services.agent.prompts.loader import load_prompt

from .. import context
from ..state import SubgraphState

logger = logging.getLogger(__name__)


def create_react_subgraph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    prompt_name: str,
    prompt_vars: dict | None = None,
) -> StateGraph:
    """Build an isolated ReAct subgraph with correct tool execution flow."""
    sys_prompt = (
        load_prompt(prompt_name, **prompt_vars)
        if prompt_vars
        else load_prompt(prompt_name)
    )
    llm_with_tools = llm.bind_tools(tools)

    async def call_model(state: SubgraphState) -> dict:
        messages, report = context.assemble_agent_messages(
            system_prompt=sys_prompt,
            messages=state["messages"],
            memory_context=state.get("memory_context"),
        )
        response = await llm_with_tools.ainvoke(messages)
        tool_names = [
            tc.get("name") for tc in getattr(response, "tool_calls", None) or []
        ]
        logger.info(
            "[%s] model response: tool_calls=%s content_len=%d",
            prompt_name,
            tool_names or None,
            len(response.content or ""),
        )
        # context_report rides along in state so api.py can surface what the
        # assembly did (memory injected / history trimmed / budgets) over SSE.
        return {"messages": [response], "context_report": report.to_dict()}

    def should_continue(state: SubgraphState) -> str:
        last_msg = state["messages"][-1]
        if getattr(last_msg, "tool_calls", None):
            if state["current_iteration"] >= state["max_iterations"]:
                return END
            return "tools"  # Route to ToolNode
        return END

    def step_counter(state: SubgraphState) -> dict:
        return {"current_iteration": state["current_iteration"] + 1}

    builder = StateGraph(SubgraphState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tools))  # ← ToolNode thực thi tool
    builder.add_node("counter", step_counter)

    builder.add_edge(START, "agent")

    # FIX: agent → tools → counter → agent (đúng thứ tự ReAct)
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",  # ← Rẽ vào ToolNode để THỰC THI tool
            END: END,
        },
    )
    builder.add_edge("tools", "counter")  # ← Sau khi tool chạy xong → tăng counter
    builder.add_edge("counter", "agent")  # ← Quay lại LLM với kết quả tool

    return builder.compile()
