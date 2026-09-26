# ============================================
# services/conversation/episodic/retriever.py
# ============================================
"""
Episode retrieval: current-thread lookup via SQL (Postgres is canonical and
the ONLY store for episodes).

Memory is INDEPENDENT PER THREAD (reference C/D pattern): each conversation
summarizes its own old messages and only that summary is injected back into
its own thread. There is no cross-thread retrieval — episodes of other
conversations are never mixed into the current prompt.
"""

import logging
from uuid import UUID, uuid5

from ..models import EpisodeSummary
from ..repository import ConversationRepository

logger = logging.getLogger(__name__)

# Deterministic namespace for episode ids. Never change this: existing rows
# were serialized with ids derived from this namespace.
EPISODIC_MEMORY_NAMESPACE = UUID("29f9e817-9ee2-4bb5-b83d-c3136f0df735")


def build_episode_id(user_id: str, thread_id: str) -> str:
    """Deterministic episode id: one canonical episode per (user, thread)."""
    return str(uuid5(EPISODIC_MEMORY_NAMESPACE, f"{user_id}|{thread_id}"))


def serialize_episode(episode: EpisodeSummary | None) -> dict:
    """
    Convert an EpisodeSummary row into the canonical episode dict.

    The dict carries the pinned response fields (episode_id, thread_id, title,
    context, summary, actions, outcome, errors, user_corrections,
    lessons_learned, open_loops, agents_involved, score, status, updated_at)
    plus ``user_id``.

    Args:
        episode: The SQL row, or None.

    Returns:
        The serialized dict (empty dict when ``episode`` is None).
    """
    if episode is None:
        return {}
    return {
        "episode_id": build_episode_id(episode.user_id, episode.thread_id),
        "user_id": episode.user_id,
        "thread_id": episode.thread_id,
        "title": episode.title,
        "context": episode.context,
        "summary": episode.summary,
        "actions": episode.actions or [],
        "outcome": episode.outcome or {},
        "errors": episode.errors or [],
        "user_corrections": episode.user_corrections or [],
        "lessons_learned": episode.lessons_learned or [],
        "open_loops": episode.open_loops or [],
        "agents_involved": episode.agents_involved or [],
        "score": None,
        "status": episode.status,
        "updated_at": episode.updated_at.isoformat() if episode.updated_at else None,
    }


class EpisodicRetriever:
    """Reads the current thread's own episode (SQL only, no vector store)."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    async def get_current_episode(self, user_id: str, thread_id: str) -> dict:
        """
        Fetch the current thread's episode summary from SQL.

        Args:
            user_id: Owner of the episode.
            thread_id: The conversation id.

        Returns:
            The serialized episode, or {} when missing or not yet summarized.
        """
        episode = await self._repository.get_episode(user_id, thread_id)
        if episode is None or episode.summarized_at is None:
            return {}
        return serialize_episode(episode)
