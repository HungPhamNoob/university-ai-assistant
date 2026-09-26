# ============================================
# services/agent/api.py
# ============================================
"""
FastAPI endpoints for SSE Streaming and HITL Resume.
Passes user context into the LangGraph configurable dictionary.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from .auth import verify_gateway_request
from .clients import sync_conversation_thread

logger = logging.getLogger(__name__)
router = APIRouter()

# SSE keepalive. Trong lúc tool call / LLM chạy lâu, stream có thể im lặng
# nhiều chục giây; ALB (idle 60s) và Kong (read_timeout) sẽ cắt kết nối nếu
# không có byte nào chảy. Frame comment ": ping" là chuẩn SSE: browser và
# parser của frontend bỏ qua (không bắt đầu bằng "data:"), nhưng proxy thấy
# kết nối vẫn sống. [PRODUCTION PATTERN] cho SSE sau reverse proxy.
HEARTBEAT_INTERVAL_SECONDS = 15.0
HEARTBEAT_FRAME = ": ping\n\n"

# Header chống buffer cho SSE qua proxy họ nginx (Kong): X-Accel-Buffering:no
# yêu cầu nginx tắt proxy buffering trên response này để event chảy real-time.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


async def with_heartbeat(
    frames: AsyncIterator[str],
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Forward SSE frames; inject a keepalive comment when the stream is quiet.

    Dùng queue + producer task vì KHÔNG được timeout trực tiếp trên
    ``__anext__`` của generator bên trong — cancel một async generator giữa
    chừng có thể làm hỏng trạng thái của nó. Producer sở hữu generator gốc;
    consumer chỉ wait-for trên queue, nên timeout chỉ ảnh hưởng tới việc đọc
    queue chứ không bao giờ chạm vào graph.

    Args:
        frames: Async iterator các SSE frame (string) từ event_generator.
        interval_seconds: Số giây im lặng tối đa trước khi chèn heartbeat.

    Yields:
        Frame gốc, xen kẽ HEARTBEAT_FRAME khi stream im lặng quá lâu.
    """
    queue: asyncio.Queue = asyncio.Queue()
    stream_done = object()  # sentinel: generator bên trong kết thúc bình thường

    async def pump_inner_stream() -> None:
        try:
            async for frame in frames:
                await queue.put(frame)
        except BaseException as error:  # noqa: BLE001 - chuyển lỗi về phía consumer
            await queue.put(error)
            return
        await queue.put(stream_done)

    producer = asyncio.create_task(pump_inner_stream())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval_seconds)
            except TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            if item is stream_done:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer


def streaming_response(event_generator: AsyncIterator[str]) -> StreamingResponse:
    """Build the SSE response: heartbeat-wrapped generator + anti-buffer headers."""
    return StreamingResponse(
        with_heartbeat(event_generator),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# Vietnamese display labels for the 'agent' SSE event emitted once per turn.
INTENT_LABELS = {
    "faq_agent": "FAQ — Chính sách nội bộ",
    "search_agent": "Web Search — Thông tin thời sự",
    "booking_agent": "Booking — Đặt phòng họp",
    "general_chat": "Trò chuyện chung",
}

# Parent-graph leaf nodes that each run exactly one answer per turn. Keying on
# their start event lets api.py emit the 'agent' event right after the router
# decided the intent and before the first subgraph token reaches the client.
LEAF_NODE_TO_INTENT = {
    "faq_node": "faq_agent",
    "search_node": "search_agent",
    "booking_node": "booking_agent",
    "chat_node": "general_chat",
}


class ChatRequest(BaseModel):
    thread_id: str
    message: str
    user_id: str = "anonymous"
    email: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    decision: dict
    # Carry the user context again: after an interrupt the graph resumes with
    # a fresh RunnableConfig, so user_id must be re-injected or the booking
    # tools would fall back to the default owner.
    user_id: str = "anonymous"
    email: str | None = None


def get_graph():
    from .main import app

    return app.state.graph


def resolve_user(
    req_user_id: str, req_email: str | None, gateway_ctx: dict
) -> tuple[str, str | None]:
    """
    Resolve the effective user identity for a chat request.

    When gateway enforcement is enabled the identity injected by the gateway
    wins; otherwise the caller-provided values are used (local CLI/eval mode).

    Args:
        req_user_id: user_id field from the request body.
        req_email: email field from the request body.
        gateway_ctx: Context returned by verify_gateway_request.

    Returns:
        Tuple (user_id, email).
    """
    if gateway_ctx.get("user_id"):
        return gateway_ctx["user_id"], gateway_ctx.get("email")
    return req_user_id, req_email


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def collect_user_assistant_pairs(messages: list) -> list[dict[str, str]]:
    """
    Reduce a LangGraph message list to plain user/assistant turns.

    Tool messages and tool-call AIMessages are internal mechanics and must
    not leak into the persisted conversation history.

    Args:
        messages: Messages from the final graph state.

    Returns:
        List of {"role": "user"|"assistant", "content": str} dicts.
    """
    pairs: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            pairs.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = str(msg.content or "").strip()
            if content:
                pairs.append({"role": "assistant", "content": content})
    return pairs


async def sync_thread_when_done(graph, config: dict, user_id: str) -> None:
    """
    Persist the thread into the Conversation service once a turn finishes.

    Skipped while the graph is paused for human approval (state.next set),
    because the turn is not complete yet. Best-effort: any error is logged
    and never breaks the chat stream.

    Args:
        graph: Compiled primary graph.
        config: RunnableConfig carrying thread_id.
        user_id: Owner of the conversation.
    """
    try:
        state = await graph.aget_state(config)
        if state.next:
            return
        pairs = collect_user_assistant_pairs(state.values.get("messages", []))
        if pairs:
            await sync_conversation_thread(
                thread_id=config["configurable"]["thread_id"],
                user_id=user_id,
                messages=pairs,
            )
    except Exception as error:  # noqa: BLE001 - history sync must never break chat
        logger.warning("Conversation history sync failed: %s", error)


@router.post("/stream")
async def stream_chat(
    req: ChatRequest,
    gateway_ctx: dict = Depends(verify_gateway_request),
    graph=Depends(get_graph),
):
    # Resolve identity (gateway wins when enforcement is enabled) and inject
    # it into the thread configuration.
    user_id, email = resolve_user(req.user_id, req.email, gateway_ctx)
    config = {
        "configurable": {
            "thread_id": req.thread_id,
            "user_id": user_id,
            "email": email,
        }
    }
    input_state = {"messages": [HumanMessage(content=req.message)]}

    async def event_generator():
        agent_emitted = False
        try:
            async for event in graph.astream_events(
                input_state, config=config, version="v2"
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    # Skip the router's internal JSON — it is not part of the answer.
                    if event.get("metadata", {}).get("langgraph_node") == "router":
                        continue
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield format_sse({"event": "token", "data": chunk.content})
                elif kind == "on_tool_start":
                    yield format_sse(
                        {
                            "event": "tool",
                            "data": {"name": event["name"], "status": "start"},
                        }
                    )
                elif kind == "on_tool_end":
                    yield format_sse(
                        {
                            "event": "tool",
                            "data": {"name": event["name"], "status": "end"},
                        }
                    )
                elif kind == "on_chain_start":
                    node = event.get("metadata", {}).get("langgraph_node")
                    if not agent_emitted and node in LEAF_NODE_TO_INTENT:
                        agent_emitted = True
                        intent = LEAF_NODE_TO_INTENT[node]
                        yield format_sse(
                            {
                                "event": "agent",
                                "data": {
                                    "name": intent,
                                    "label": INTENT_LABELS[intent],
                                },
                            }
                        )

            # Check for interrupts after stream completes
            state = await graph.aget_state(config)
            if state.next:
                interrupt_data = (
                    state.tasks[0].interrupts[0]
                    if state.tasks and state.tasks[0].interrupts
                    else {}
                )
                yield format_sse({"event": "interrupt", "data": interrupt_data.value})
            else:
                # Turn finished: tell the client what context assembly did
                # (memory injected / history trimmed / budgets), then persist.
                report = state.values.get("context_report")
                if report:
                    yield format_sse({"event": "context", "data": report})
                await sync_thread_when_done(graph, config, user_id)
                yield format_sse({"event": "done", "data": "Completed"})

        except Exception as e:
            logger.exception("Stream error")
            yield format_sse({"event": "error", "data": str(e)})

    return streaming_response(event_generator())


@router.post("/resume")
async def resume_chat(
    req: ResumeRequest,
    gateway_ctx: dict = Depends(verify_gateway_request),
    graph=Depends(get_graph),
):
    user_id, email = resolve_user(req.user_id, req.email, gateway_ctx)
    config = {
        "configurable": {
            "thread_id": req.thread_id,
            "user_id": user_id,
            "email": email,
        }
    }
    command = Command(resume=req.decision)

    async def event_generator():
        agent_emitted = False
        try:
            async for event in graph.astream_events(
                command, config=config, version="v2"
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield format_sse({"event": "token", "data": chunk.content})
                elif kind == "on_tool_start":
                    yield format_sse(
                        {
                            "event": "tool",
                            "data": {"name": event["name"], "status": "start"},
                        }
                    )
                elif kind == "on_tool_end":
                    yield format_sse(
                        {
                            "event": "tool",
                            "data": {"name": event["name"], "status": "end"},
                        }
                    )
                elif kind == "on_chain_start":
                    node = event.get("metadata", {}).get("langgraph_node")
                    if not agent_emitted and node in LEAF_NODE_TO_INTENT:
                        agent_emitted = True
                        intent = LEAF_NODE_TO_INTENT[node]
                        yield format_sse(
                            {
                                "event": "agent",
                                "data": {
                                    "name": intent,
                                    "label": INTENT_LABELS[intent],
                                },
                            }
                        )

            state = await graph.aget_state(config)
            if state.next:
                # The resumed run paused at ANOTHER human-in-the-loop step
                # (e.g. booking conflict -> retry needs a second approval).
                # Surface it so the client can ask the human again.
                interrupt_data = (
                    state.tasks[0].interrupts[0]
                    if state.tasks and state.tasks[0].interrupts
                    else {}
                )
                yield format_sse({"event": "interrupt", "data": interrupt_data.value})
            else:
                # Turn finished after the HITL resume: context report first,
                # then persist the history.
                report = state.values.get("context_report")
                if report:
                    yield format_sse({"event": "context", "data": report})
                await sync_thread_when_done(graph, config, user_id)
                yield format_sse({"event": "done", "data": "Completed"})
        except Exception as e:  # noqa: BLE001 - serialize any failure into the SSE error event
            yield format_sse({"event": "error", "data": str(e)})

    return streaming_response(event_generator())
