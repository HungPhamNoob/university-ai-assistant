# ============================================
# services/agent/graph.py
# ============================================
"""
Parent Graph: Routes intents to specialized subgraphs.
Implements clean_messages and delta return to maintain different-state isolation.
Maps context (user_id, email) from Parent to Child state.
"""

import json
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from services.agent.prompts.loader import load_prompt

from .agents.booking import build_booking_graph
from .agents.faq import build_faq_graph
from .agents.search import build_search_graph
from .clients import fetch_memory_context
from .context import assemble_agent_messages
from .state import PrimaryState

logger = logging.getLogger(__name__)

VALID_INTENTS = {"faq_agent", "search_agent", "booking_agent", "general_chat"}

# Deterministic routing signals used ONLY when the router LLM fails to emit
# valid JSON. Order matters: booking (actionable writes) first, then search,
# then faq. Kept conservative — the LLM router stays the primary mechanism.
_BOOKING_SIGNALS = (
    "đặt phòng",
    "dat phong",
    "book phòng",
    "book phong",
    "booking",
    "phòng họp",
    "phong hop",
    "hủy lịch đặt",
    "huy lich dat",
    "hủy phòng",
    "huy phong",
    "hủy lịch",
    "huy lich",
    "đặt lại",
    "dat lai",
    "book lại",
    "rebook",
    "đặt giúp",
    "dat giup",
    "đổi lịch",
    "doi lich",
    "còn phòng",
    "con phong",
    "phòng trống",
    "lịch đặt phòng",
    "lich dat phong",
    "muốn book",
    "muon book",
    "đã đặt những phòng",
    "xem lại lịch",
    "đã đặt",
    "lich cua toi",
    "lịch của tôi",
    "các lịch",
    "lịch đã đặt",
    "cuộc họp đã đặt",
    "vừa đặt",
    "hủy cái",
    "hủy giúp",
    "huy giup",
    "huy giùm",
    "hủy giùm",
    # English / no-diacritics spellings users actually type
    "huy room",
    "hủy room",
    "huỷ room",
    "cancel room",
    "cancel booking",
    "book room",
    "reserve room",
    "meeting room",
    "room booking",
    "huy booking",
    "hủy booking",
    "mã đặt phòng",
    "ma dat phong",
    "mã booking",
    "ma booking",
    "cancel my",
    "my booking",
)

# A booking id like bk-1f962b27 is an unambiguous booking-domain reference.
_BOOKING_ID_RE = re.compile(r"\bbk-[0-9a-z]{6,}\b", re.IGNORECASE)
_SEARCH_SIGNALS = (
    "thời tiết",
    "thoi tiet",
    "giá vàng",
    "gia vang",
    "cổ phiếu",
    "co phieu",
    "tỷ giá",
    "ti gia",
    "tin tức",
    "tin tuc",
    "mới nhất",
    "moi nhat",
    "tuần qua",
    "bây giờ",
    "hien tai",
    "hiện tại",
    "internet",
    "ngoại tệ",
    "sáng nay",
    "chiều nay",
)
_FAQ_SIGNALS = (
    "chính sách",
    "chinh sach",
    "quy định",
    "quy dinh",
    "học thuật",
    "hoc thuat",
    "sinh viên",
    "sinh vien",
    "giảng viên",
    "giang vien",
    "quyền riêng tư",
    "quyen rieng tu",
    "an toàn",
    "an toan",
    "trí tuệ nhân tạo",
    "tri tue nhan tao",
    "đào tạo",
    "dao tao",
    "nghiên cứu",
    "nghien cuu",
    "nội bộ",
    "noi bo",
    "UET",
    "nhân quyền",
    "quấy rối",
    "cưỡng bức",
    "gian lận",
    "đạo đức",
    "đối thoại",
    "ban giám đốc",
)


def infer_intent_from_text(text: str) -> str:
    """
    Keyword-based intent guess, used only when the router LLM output is unusable.

    Args:
        text: Latest user message.

    Returns:
        Best-effort intent; general_chat when no signal matches.
    """
    normalized = f" {(text or '').lower()} "
    # Booking ids (bk-xxxx) are unambiguous — always a booking request.
    if text and _BOOKING_ID_RE.search(text):
        return "booking_agent"
    if any(signal in normalized for signal in _BOOKING_SIGNALS):
        return "booking_agent"
    if any(signal in normalized for signal in _SEARCH_SIGNALS):
        return "search_agent"
    if any(signal in normalized for signal in _FAQ_SIGNALS):
        return "faq_agent"
    return "general_chat"


def parse_router_intent(content: str) -> str | None:
    """
    Robustly extract the intent from the router LLM output.

    Some providers wrap the JSON in prose or code fences, so plain
    json.loads is not enough. Returns None when no valid intent can be
    recovered; the caller then applies the keyword fallback.

    Args:
        content: Raw router model output.

    Returns:
        One of the four valid agent names, or None when unparseable.
    """
    text = (content or "").strip().replace("```json", "").replace("```", "")

    candidates = [text]
    brace_match = re.search(r'\{[^{}]*"intent"[^{}]*\}', text, re.DOTALL)
    if brace_match:
        candidates.insert(0, brace_match.group(0))

    for candidate in candidates:
        try:
            intent = json.loads(candidate).get("intent")
            if intent in VALID_INTENTS:
                return intent
        except (ValueError, AttributeError):
            continue

    # Last resort: the model printed a valid agent name somewhere in prose.
    for name in ("booking_agent", "faq_agent", "search_agent", "general_chat"):
        if name in text:
            return name

    return None


def clean_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Filter out ToolMessages and AIMessages with tool_calls to prevent orphan errors."""
    cleaned = []
    for msg in messages:
        if (
            isinstance(msg, HumanMessage)
            or isinstance(msg, AIMessage)
            and not getattr(msg, "tool_calls", None)
        ):
            cleaned.append(msg)
    return cleaned


def _latest_human_text(state: PrimaryState) -> str:
    """Return the text of the most recent HumanMessage, or '' when absent."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


async def _fetch_memory_context(
    state: PrimaryState, config: RunnableConfig
) -> dict | None:
    """
    Fetch episodic memory for the turn and return the memory context dict.

    Memory is optional by design: a missing identity, an empty query, or an
    unreachable conversation service all degrade to None so the turn proceeds
    exactly as if no memory existed.
    """
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    user_id = configurable.get("user_id", "anonymous")
    query = _latest_human_text(state)
    if not thread_id or not query:
        return None
    try:
        return await fetch_memory_context(thread_id, user_id, query)
    except Exception as error:  # noqa: BLE001 - memory must never break a turn
        logger.warning("Memory context fetch failed: %s", error)
        return None


def build_primary_graph(llm: BaseChatModel, checkpointer: BaseCheckpointSaver):
    """Build the parent graph."""
    faq_graph = build_faq_graph(llm)
    search_graph = build_search_graph(llm)
    booking_graph = build_booking_graph(llm)

    sys_prompt = load_prompt("primary")
    general_prompt = load_prompt("general")

    async def router_node(state: PrimaryState) -> dict:
        messages = [SystemMessage(content=sys_prompt)] + state["messages"]
        response = await llm.ainvoke(messages)
        intent = parse_router_intent(
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        if intent is None:
            # The router LLM ignored its contract (e.g. answered the user
            # directly instead of emitting JSON). Fall back to deterministic
            # keyword routing on the latest user message.
            last_human = ""
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    last_human = str(msg.content)
                    break
            intent = infer_intent_from_text(last_human)
            logger.warning(
                "Router JSON parse failed; keyword fallback -> %s. Raw: %s",
                intent,
                str(response.content)[:200],
            )
        logger.info("Router decision: %s", intent)
        return {"active_agent": intent}

    async def general_chat_node(state: PrimaryState, config: RunnableConfig) -> dict:
        # Generate the real answer for greetings/chit-chat (router only returns JSON).
        # General chat ALSO goes through context assembly + episodic memory:
        # within THIS thread's own rolling summary (independent-thread policy),
        # a long conversation still has its old messages represented.
        memory_context = await _fetch_memory_context(state, config)
        messages, report = assemble_agent_messages(
            system_prompt=general_prompt,
            messages=clean_messages(state["messages"]),
            memory_context=memory_context,
        )
        response = await llm.ainvoke(messages)
        return {"messages": [response], "context_report": report.to_dict()}

    async def call_subgraph(
        subgraph, state: PrimaryState, config: RunnableConfig
    ) -> dict:
        # Map Parent State -> Child State (Context Injection)
        memory_context = await _fetch_memory_context(state, config)
        child_input = {
            "messages": clean_messages(state["messages"]),
            "max_iterations": 5,
            "current_iteration": 0,
            "memory_context": memory_context,
            # "user_id": state.get("user_id"),
            # "email": state.get("email")
        }
        child_output = await subgraph.ainvoke(child_input, config=config)

        # Only return the DELTA messages to prevent state bloat
        new_msgs = child_output["messages"][len(child_input["messages"]) :]
        return {
            "messages": new_msgs,
            "active_agent": None,
            "context_report": child_output.get("context_report"),
        }

    async def call_faq(state: PrimaryState, config: RunnableConfig) -> dict:
        return await call_subgraph(faq_graph, state, config)

    async def call_search(state: PrimaryState, config: RunnableConfig) -> dict:
        return await call_subgraph(search_graph, state, config)

    async def call_booking(state: PrimaryState, config: RunnableConfig) -> dict:
        return await call_subgraph(booking_graph, state, config)

    def route_intent(state: PrimaryState) -> str:
        agent = state.get("active_agent")
        if not agent:
            return END
        mapping = {
            "faq_agent": "faq_node",
            "search_agent": "search_node",
            "booking_agent": "booking_node",
            "general_chat": "chat_node",
        }
        return mapping.get(agent, END)

    builder = StateGraph(PrimaryState)
    builder.add_node("router", router_node)
    builder.add_node("chat_node", general_chat_node)
    builder.add_node("faq_node", call_faq)
    builder.add_node("search_node", call_search)
    builder.add_node("booking_node", call_booking)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_intent,
        {
            "faq_node": "faq_node",
            "search_node": "search_node",
            "booking_node": "booking_node",
            "chat_node": "chat_node",
            END: END,
        },
    )

    builder.add_edge("chat_node", END)
    builder.add_edge("faq_node", END)
    builder.add_edge("search_node", END)
    builder.add_edge("booking_node", END)

    # Checkpointer is ONLY attached to the parent graph
    return builder.compile(checkpointer=checkpointer)
