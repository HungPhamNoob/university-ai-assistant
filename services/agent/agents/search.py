# ============================================
# services/agent/agents/search.py
# ============================================
"""Search Agent: 1 Tool (Tavily Web Search) với bounded wait.

Vì sao phải wrap TavilySearchResults:
- LangChain community gọi Tavily qua aiohttp KHÔNG set timeout -> mặc định
  aiohttp là 5 phút. Một cú search treo = SSE stream im lặng 5 phút.
- ALB (idle 60s) và Kong (read_timeout 60s) sẽ cắt kết nối trước đó, client
  nhận ERR_INCOMPLETE_CHUNKED_ENCODING, task bị cancel (CancelledError).
- Với bounded wait, tool thất bại nhanh và TRẢ VỀ message mô tả lỗi để LLM
  báo cho user, thay vì làm chết cả stream. Đây là cùng pattern bounded-wait
  mà project dùng cho các LLM call phụ (xem EPISODIC_LLM_TIMEOUT_SECONDS).
"""

import asyncio
from datetime import datetime

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from ..config import settings
from .base import create_react_subgraph


def build_search_web_tool(timeout_seconds: float | None = None):
    """Create the `search_web` tool: Tavily search wrapped in a hard timeout.

    Args:
        timeout_seconds: Override for WEB_SEARCH_TIMEOUT_SECONDS (used by tests).

    Returns:
        An async LangChain tool named ``search_web`` that never raises for
        network problems — failures come back as a plain-text message so the
        ReAct loop can continue and the LLM can inform the user.
    """
    if timeout_seconds is None:
        timeout_seconds = settings.WEB_SEARCH_TIMEOUT_SECONDS

    tavily = TavilySearchResults(
        max_results=3,
        api_key=settings.TAVILY_API_KEY,
    )

    @tool("search_web")
    async def search_web(query: str) -> str:
        """Search the internet for real-time information, news, or public data."""
        try:
            results = await asyncio.wait_for(
                tavily.ainvoke(query),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return (
                f"ERROR: web search timed out after {timeout_seconds:.0f}s — the search "
                "provider did not respond. Tell the user web search is temporarily "
                "unavailable and suggest retrying later. Do NOT call search_web again."
            )
        except Exception as error:  # noqa: BLE001 - tool lỗi phải thành message, không giết stream
            return (
                f"ERROR: web search failed ({error}). Tell the user web search is "
                "temporarily unavailable. Do NOT call search_web again."
            )
        return results if isinstance(results, str) else str(results)

    return search_web


def get_search_tools():
    return [build_search_web_tool()]


def build_search_graph(llm: BaseChatModel):
    return create_react_subgraph(
        llm,
        get_search_tools(),
        "search",
        prompt_vars={"today": datetime.now().date().isoformat()},
    )
