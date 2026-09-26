# ============================================
# tests/test_graph.py
# Offline smoke tests for the LangGraph agent graph.
#
#   uv run pytest tests/test_graph.py -v
#
# No external service is needed: the LLM is replaced by a scripted fake,
# so these tests run in CI as well. They cover:
#   1. parse_router_intent (clean JSON, fenced JSON, prose, invalid).
#   2. infer_intent_from_text keyword fallback.
#   3. Router -> general_chat_node end-to-end.
#   4. Router -> faq_subgraph end-to-end.
#   5. Router -> search_subgraph end-to-end.
#   6. Booking flow: tool call -> HITL interrupt -> resume with rejection.
# ============================================
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Make the project root importable when pytest is run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fallback values so the service configs import cleanly without a .env file.
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("LLM_MODEL", "test-model")

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import Field

from services.agent.agents import booking as booking_agent
from services.agent.graph import (
    build_primary_graph,
    infer_intent_from_text,
    parse_router_intent,
)

# Router intents are plain strings (see services/agent/graph.py VALID_INTENTS).
FAQ = "faq_agent"
SEARCH = "search_agent"
BOOKING = "booking_agent"
GENERAL = "general_chat"


class ScriptedFakeChatModel(BaseChatModel):
    """A chat model that returns pre-scripted answers in order (no network)."""

    responses: list[BaseMessage]
    recorded: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.recorded.append(list(messages))
        if not self.responses:
            raise RuntimeError("ScriptedFakeChatModel ran out of scripted responses")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedFakeChatModel":
        # The react subgraphs bind their tools, but the scripted answers are
        # fixed up-front, so binding is a no-op here.
        return self


def make_config(thread_id: str) -> dict:
    """Config for a fresh graph thread per test."""
    return {"configurable": {"thread_id": thread_id}}


# ---------- 1. parse_router_intent ----------
def test_parse_router_intent_clean_json() -> None:
    assert parse_router_intent('{"intent": "faq_agent"}') == FAQ


def test_parse_router_intent_fenced_json() -> None:
    raw = 'Here is my decision:\n```json\n{"intent": "booking_agent"}\n```\nDone.'
    assert parse_router_intent(raw) == BOOKING


def test_parse_router_intent_json_inside_prose() -> None:
    raw = 'The user wants to search, so {"intent": "search_agent"} is my choice.'
    assert parse_router_intent(raw) == SEARCH


def test_parse_router_intent_plain_intent_name() -> None:
    assert parse_router_intent("general_chat") == GENERAL


def test_parse_router_intent_invalid_returns_none() -> None:
    assert parse_router_intent("xin chào bạn") is None
    assert parse_router_intent("") is None


# ---------- 2. infer_intent_from_text ----------
def test_infer_intent_booking_keyword() -> None:
    assert infer_intent_from_text("Tôi muốn đặt phòng họp lúc 9h") == BOOKING


def test_infer_intent_faq_keyword() -> None:
    assert infer_intent_from_text("Chính sách sử dụng AI như thế nào?") == FAQ


def test_infer_intent_search_keyword() -> None:
    assert infer_intent_from_text("Tìm kiếm tin tức mới nhất") == SEARCH


def test_infer_intent_default_general() -> None:
    assert infer_intent_from_text("Xin chào") == GENERAL


# ---------- 3. Router -> general_chat_node ----------
@pytest.mark.asyncio
async def test_graph_routes_general_chat() -> None:
    final_answer = "Xin chào! Tôi có thể giúp gì cho bạn?"
    fake = ScriptedFakeChatModel(
        responses=[
            AIMessage(content='{"intent": "general_chat"}'),  # router decision
            AIMessage(content=final_answer),  # chat_subgraph answer
        ]
    )
    graph = build_primary_graph(fake, MemorySaver())

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Xin chào")]},
        config=make_config("test-general-chat"),
    )

    assert result["messages"][-1].content == final_answer
    # chat_node does not go through call_subgraph, so active_agent keeps
    # the router decision (only subgraph calls reset it to None).
    assert result.get("active_agent") == "general_chat"
    # Two LLM calls: router + chat answer.
    assert len(fake.recorded) == 2


# ---------- 4. Router -> faq_subgraph ----------
@pytest.mark.asyncio
async def test_graph_routes_faq_subgraph() -> None:
    final_answer = (
        "Khung tham chiếu yêu cầu có người giám sát quyết định AI rủi ro cao."
    )
    fake = ScriptedFakeChatModel(
        responses=[
            AIMessage(content='{"intent": "faq_agent"}'),
            AIMessage(content=final_answer),
        ]
    )
    graph = build_primary_graph(fake, MemorySaver())

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Chính sách dùng AI thế nào?")]},
        config=make_config("test-faq-route"),
    )

    assert result["messages"][-1].content == final_answer
    # The second LLM call happened inside the FAQ subgraph, so it received
    # the FAQ system prompt as its first message.
    assert len(fake.recorded) == 2
    assert "UET knowledge and policy agent" in fake.recorded[1][0].content


# ---------- 5. Router -> search_subgraph ----------
@pytest.mark.asyncio
async def test_graph_routes_search_subgraph() -> None:
    final_answer = "Đây là kết quả tìm kiếm trên web."
    fake = ScriptedFakeChatModel(
        responses=[
            AIMessage(content='{"intent": "search_agent"}'),
            AIMessage(content=final_answer),
        ]
    )
    graph = build_primary_graph(fake, MemorySaver())

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Tìm kiếm tin tức AI mới nhất")]},
        config=make_config("test-search-route"),
    )

    assert result["messages"][-1].content == final_answer
    assert len(fake.recorded) == 2
    assert "Live web search agent" in fake.recorded[1][0].content


# ---------- 6. Booking flow: tool call -> HITL interrupt -> resume ----------
@pytest.mark.asyncio
async def test_booking_flow_interrupt_and_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_answer = "Đã hủy yêu cầu đặt phòng theo quyết định của bạn."

    # Keep this graph test independent from bookings left by local/E2E runs.
    # Availability behavior has its own service tests; here we only exercise
    # the graph's tool -> interrupt -> reject/resume path.
    async def available_slot(*args: Any, **kwargs: Any) -> dict:
        return {"status": "success", "available": True}

    monkeypatch.setattr(booking_agent, "check_booking_availability", available_slot)

    # Ngày mai 09:00 — KHÔNG hardcode ngày: ngày cố định sẽ trở thành "quá khứ"
    # theo thời gian, tool trả invalid_time đúng nghiệp vụ và không interrupt.
    tomorrow_9am = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 09:00")
    fake = ScriptedFakeChatModel(
        responses=[
            # 1) Router routes to the booking agent.
            AIMessage(content='{"intent": "booking_agent"}'),
            # 2) Booking agent decides to call book_meeting_room.
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "book_meeting_room",
                        "args": {
                            "room_name": "GD3-402",
                            "start_time": tomorrow_9am,
                            "duration_minutes": 60,
                            "purpose": "Họp team hàng tuần",
                        },
                        "id": "call_test_1",
                        "type": "tool_call",
                    }
                ],
            ),
            # 3) After the user rejects, the agent reports back.
            AIMessage(content=final_answer),
        ]
    )
    graph = build_primary_graph(fake, MemorySaver())
    config = make_config("test-booking-hitl")

    # First run stops at the interrupt() inside book_meeting_room,
    # BEFORE any write to the booking database.
    result = await graph.ainvoke(
        {
            "messages": [
                HumanMessage(content="Đặt phòng GD3-402 lúc 9h ngày mai để họp team")
            ]
        },
        config=config,
    )

    interrupts = result.get("__interrupt__")
    assert interrupts, "the booking tool must pause for human approval"
    payload = interrupts[0].value
    assert payload["action"] == "book_room"
    assert payload["details"]["room"] == "GD3-402"
    assert "Xác nhận đặt phòng" in payload["message"]

    # Resume with a rejection: the tool returns a 'rejected' JSON result
    # without touching the booking service at all.
    result2 = await graph.ainvoke(Command(resume={"approved": False}), config=config)

    tool_messages = [m for m in result2["messages"] if m.type == "tool"]
    assert len(tool_messages) == 1
    assert '"status": "rejected"' in tool_messages[0].content

    assert result2["messages"][-1].content == final_answer
    # Subgraph completed, so the parent state is reset.
    assert result2.get("active_agent") is None


# ---------- 7. SSE heartbeat + bounded-wait web search ----------
# Regression cho bug production: Tavily treo -> SSE stream im lặng -> ALB/Kong
# (idle 60s) cắt kết nối -> browser nhận ERR_INCOMPLETE_CHUNKED_ENCODING,
# agent task bị cancel (CancelledError). Hai lớp phòng vệ được test ở đây:
#   a) with_heartbeat chèn frame keepalive khi stream im lặng;
#   b) search_web tool cắt Tavily bằng bounded wait, trả message thay vì raise.
import asyncio
import time


@pytest.mark.asyncio
async def test_sse_heartbeat_during_silence() -> None:
    from services.agent.api import HEARTBEAT_FRAME, with_heartbeat

    async def quiet_stream():
        yield "data: 1\n\n"
        await asyncio.sleep(0.5)  # im lặng ~3 interval heartbeat
        yield "data: 2\n\n"

    frames = [f async for f in with_heartbeat(quiet_stream(), interval_seconds=0.15)]

    assert frames[0] == "data: 1\n\n"
    assert frames[-1] == "data: 2\n\n"
    assert frames.count(HEARTBEAT_FRAME) >= 2, "phải có keepalive trong lúc im lặng"


@pytest.mark.asyncio
async def test_sse_heartbeat_propagates_stream_errors() -> None:
    from services.agent.api import with_heartbeat

    async def broken_stream():
        yield "data: 1\n\n"
        raise RuntimeError("graph exploded")

    with pytest.raises(RuntimeError, match="graph exploded"):
        async for _ in with_heartbeat(broken_stream(), interval_seconds=0.15):
            pass


@pytest.mark.asyncio
async def test_search_web_tool_bounded_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_community.tools.tavily_search import TavilySearchResults

    from services.agent.agents.search import build_search_web_tool

    async def hang(*args, **kwargs):
        await asyncio.sleep(30)  # Tavily "treo" như incident thật

    monkeypatch.setattr(TavilySearchResults, "ainvoke", hang)

    tool_obj = build_search_web_tool(timeout_seconds=0.2)
    started = time.monotonic()
    result = await tool_obj.ainvoke("giá cổ phiếu UET hôm nay")
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"bounded wait phải cắt sớm, thực tế {elapsed:.1f}s"
    assert "timed out" in str(result).lower()
