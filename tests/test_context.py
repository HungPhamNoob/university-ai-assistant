import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.agent import context


def test_large_tool_result_keeps_current_user_turn(monkeypatch) -> None:
    monkeypatch.setattr(
        context,
        "get_token_budget",
        lambda: context.TokenBudget(
            system_prompt=100,
            history=300,
            retrieved_docs=1_000,
            tool_outputs=500,
            reserve=100,
            context_limit=1_000,
        ),
    )
    messages = [
        HumanMessage(content="Thời tiết Hà Nội ngày mai như thế nào?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_web",
                    "args": {"query": "Hà Nội weather tomorrow"},
                    "id": "call-weather",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="dự báo thời tiết Hà Nội có mưa " * 1_000,
            tool_call_id="call-weather",
        ),
    ]

    assembled, report = context.assemble_agent_messages(
        system_prompt="Bạn là trợ lý tìm kiếm.",
        messages=messages,
    )

    history = assembled[1:]
    assert [message.type for message in history] == ["human", "ai", "tool"]
    assert history[0].content == messages[0].content
    assert report.tool_outputs_capped == 1
    assert report.history_trimmed is False
