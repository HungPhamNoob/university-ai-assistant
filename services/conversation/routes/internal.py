# ============================================
# services/conversation/routes/internal.py
# ============================================
"""
Internal endpoints for service-to-service calls (agent -> conversation).
Every route requires the shared X-Internal-Api-Token header.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import verify_internal_token
from ..schemas import MemoryContextResponse, SyncMessagesRequest, SyncResult
from ..service import ConversationNotFoundError, ConversationService

router = APIRouter(dependencies=[Depends(verify_internal_token)])


def get_service(request: Request) -> ConversationService:
    """
    Resolve the ConversationService created at application startup.

    Args:
        request: Incoming HTTP request carrying the application state.

    Returns:
        The shared ConversationService.
    """
    return request.app.state.conversation_service


@router.put("/{conversation_id}/messages", response_model=SyncResult)
async def sync_messages(
    conversation_id: str,
    payload: SyncMessagesRequest,
    service: ConversationService = Depends(get_service),
) -> SyncResult:
    """
    Synchronize a conversation's stored messages with the agent thread.

    Semantics: identical -> skip, stored prefix -> append, else -> replace.

    Args:
        conversation_id: Unique conversation identifier.
        payload: Incoming messages plus optional summarize flag.
        service: Injected use-case service.

    Returns:
        SyncResult with the action taken (skip/append/replace).
    """
    try:
        return await service.sync_messages(conversation_id, payload)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{conversation_id}/memory", response_model=MemoryContextResponse)
async def get_memory(
    conversation_id: str,
    user_id: str,
    request: Request,
    query: str = "",
) -> MemoryContextResponse:
    """
    Return the episodic memory context for the start of an agent turn.

    Independent-thread policy (reference C/D): only THIS conversation's own
    rolling episode is returned — episodes of other threads are never shared.

    Args:
        conversation_id: The thread (== conversation) id being answered.
        user_id: Owner of the thread (required; missing -> 422).
        query: Current user query (accepted for API stability; unused since
            cross-thread similarity search was removed).
        request: Incoming request carrying the application state.

    Returns:
        The current thread's episode ({} inside when not summarized yet).
    """
    episodic = request.app.state.episodic_service
    if episodic is None:
        return MemoryContextResponse()
    try:
        context = await episodic.build_memory_context(user_id, conversation_id, query)
    except Exception:  # noqa: BLE001 - missing optional deps must not 500
        return MemoryContextResponse()
    return MemoryContextResponse(**context)
