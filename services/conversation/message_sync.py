# ============================================
# services/conversation/message_sync.py
# ============================================
"""
Message synchronization between the agent thread and the stored conversation.

Semantics (per hint.md):
- stored == incoming               -> skip   (nothing to do)
- stored is a prefix of incoming   -> append (only the new tail)
- anything else                    -> replace (full rewrite)
"""

import logging

from .repository import ConversationRepository

logger = logging.getLogger(__name__)


def _normalize_pairs(messages: list[dict]) -> list[tuple[str, str]]:
    """
    Reduce message dicts to comparable (role, content) tuples.

    Args:
        messages: List of {"role": str, "content": str} dicts.

    Returns:
        List of (role, content) tuples.
    """
    return [
        (str(item.get("role", "user")), str(item.get("content", "")))
        for item in messages
    ]


async def sync_messages(
    repository: ConversationRepository, conversation_id: str, incoming: list[dict]
) -> str:
    """
    Align the stored messages with the incoming agent thread.

    Args:
        repository: Data access object for conversations/messages.
        conversation_id: Unique conversation identifier.
        incoming: Incoming messages as {"role": str, "content": str} dicts.

    Returns:
        The action taken: 'skip', 'append' or 'replace'.
    """
    stored = await repository.list_messages(conversation_id)
    stored_pairs = [(item.role, item.content) for item in stored]
    incoming_pairs = _normalize_pairs(incoming)

    if incoming_pairs == stored_pairs:
        action = "skip"
    elif (
        len(incoming_pairs) > len(stored_pairs)
        and incoming_pairs[: len(stored_pairs)] == stored_pairs
    ):
        action = "append"
        await repository.append_messages(conversation_id, incoming[len(stored_pairs) :])
    else:
        action = "replace"
        await repository.replace_messages(conversation_id, incoming)

    logger.info(
        "Message sync id=%s action=%s count=%d", conversation_id, action, len(incoming)
    )
    return action
