# ============================================
# services/agent/agents/faq.py
# ============================================
"""UET knowledge agent backed by the internal RAG index."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from ..clients import search_kb
from .base import create_react_subgraph


@tool
async def search_uet_knowledge(query: str) -> str:
    """Search UET institutional and academic-community reference documents."""
    return await search_kb(query)


def get_faq_tools():
    return [search_uet_knowledge]


def build_faq_graph(llm: BaseChatModel):
    return create_react_subgraph(llm, get_faq_tools(), "faq")
