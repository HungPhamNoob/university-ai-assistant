# ============================================
# services/conversation/routes/public.py
# ============================================
"""
User-facing HTTP endpoints of the Conversation service.

- POST   /conversations            create
- GET    /conversations?user_id=   list of one user
- GET    /conversations/{id}       one header (owner only)
- DELETE /conversations/{id}       delete (cascade messages, owner only)
- GET    /conversations/{id}/messages  message history (owner only)
- POST   /conversations/{id}/summarize force episodic summarize (owner only)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..schemas import ConversationSummary, CreateConversationRequest, MessageDTO
from ..service import ConversationNotFoundError, ConversationService

router = APIRouter()


def get_service(request: Request) -> ConversationService:
    """
    Resolve the ConversationService created at application startup.

    Args:
        request: Incoming HTTP request carrying the application state.

    Returns:
        The shared ConversationService.
    """
    return request.app.state.conversation_service


def resolve_user_id(request: Request, query_user_id: str | None) -> str:
    """
    Resolve the requesting user's identity.

    The X-User-Id header ALWAYS wins: through the gateway it is overwritten
    by Kong from the verified JWT; the query param stays as a legacy fallback
    for direct internal calls. Same policy as the Booking service.

    Args:
        request: Incoming HTTP request.
        query_user_id: Legacy ?user_id= query parameter.

    Returns:
        The effective user id.

    Raises:
        HTTPException: 400 when neither source carries an identity.
    """
    user_id = request.headers.get("X-User-Id") or query_user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user identity (X-User-Id)")
    return user_id


async def require_owner(
    service: ConversationService, conversation_id: str, user_id: str
) -> None:
    """
    Enforce conversation ownership; map service errors to HTTP status codes.

    Raises:
        HTTPException: 404 when missing, 403 when owned by someone else.
    """
    try:
        await service.require_owner(conversation_id, user_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    service: ConversationService = Depends(get_service),
) -> ConversationSummary:
    """
    Create a new conversation.

    Args:
        payload: Creation data (user_id, title).
        service: Injected use-case service.

    Returns:
        The created conversation header.
    """
    return await service.create_conversation(payload)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> list[ConversationSummary]:
    """
    List all conversations of the requesting user (never of another user).

    Args:
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        Conversation headers, newest activity first.
    """
    return await service.list_conversations(resolve_user_id(request, user_id))


@router.get("/{conversation_id}", response_model=ConversationSummary)
async def get_conversation(
    conversation_id: str,
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> ConversationSummary:
    """
    Fetch one conversation header — owner only.

    Args:
        conversation_id: Unique conversation identifier.
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        The conversation header.
    """
    await require_owner(service, conversation_id, resolve_user_id(request, user_id))
    try:
        return await service.get_conversation(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> dict:
    """
    Delete one conversation and all of its messages — owner only.

    Args:
        conversation_id: Unique conversation identifier.
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        Confirmation payload.
    """
    await require_owner(service, conversation_id, resolve_user_id(request, user_id))
    deleted = await service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"message": "Conversation deleted", "conversation_id": conversation_id}


@router.post("/{conversation_id}/summarize", status_code=202)
async def summarize_conversation(
    conversation_id: str,
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> dict:
    """
    Start a BACKGROUND episodic summarize job for one conversation,
    bypassing the EPISODIC_MESSAGE_THRESHOLD roll-up (the UI "Tóm tắt" button).

    Returns 202 immediately with the job state; the caller polls
    GET /conversations/{id}/summarize/status until state becomes 'done' or
    'error'. Keeping the LLM call off the request thread means the app stays
    fully responsive (message rendering, chat, ...) while summarizing.

    Args:
        conversation_id: Conversation to summarize.
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        Job dict: {state, conversation_id, started_at, finished_at, error,
        episode, total_messages}.
    """
    owner = resolve_user_id(request, user_id)
    try:
        return await service.start_summarize_job(conversation_id, owner)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{conversation_id}/summarize/status")
async def summarize_status(
    conversation_id: str,
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> dict:
    """
    Poll the state of the summarize job of one conversation (owner only).

    Args:
        conversation_id: Conversation being summarized.
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        Job dict; state is one of {'idle', 'running', 'done', 'error'}.
    """
    owner = resolve_user_id(request, user_id)
    try:
        return await service.summarize_job_status(conversation_id, owner)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.get("/{conversation_id}/messages", response_model=list[MessageDTO])
async def list_messages(
    conversation_id: str,
    request: Request,
    service: ConversationService = Depends(get_service),
    user_id: str | None = Query(default=None),
) -> list[MessageDTO]:
    """
    Fetch the message history of one conversation — owner only.

    Args:
        conversation_id: Unique conversation identifier.
        request: Incoming HTTP request (trusted X-User-Id header).
        service: Injected use-case service.
        user_id: Legacy query parameter fallback.

    Returns:
        Messages in chronological order.
    """
    await require_owner(service, conversation_id, resolve_user_id(request, user_id))
    try:
        return await service.list_messages(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
