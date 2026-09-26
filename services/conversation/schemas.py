# ============================================
# services/conversation/schemas.py
# ============================================
"""
Pydantic request/response schemas of the Conversation service API.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    """Request body for creating a conversation."""

    user_id: str = Field(..., min_length=1, description="Owner of the conversation")
    title: str = Field("New conversation", max_length=255, description="Display title")


class ConversationSummary(BaseModel):
    """Lightweight conversation header returned by list endpoints."""

    conversation_id: str
    user_id: str
    title: str
    summary: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageDTO(BaseModel):
    """One stored chat message."""

    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncMessagesRequest(BaseModel):
    """Payload used by the agent service to synchronize a thread's messages."""

    messages: list[dict] = Field(
        ...,
        description='List of {"role": "user"|"assistant", "content": str}',
    )
    user_id: str = Field(
        "anonymous",
        description="Owner of the conversation (used when it is auto-created).",
    )
    title: str = Field(
        "Agent conversation",
        description="Title used when the conversation is auto-created.",
    )


class SyncResult(BaseModel):
    """Outcome of one sync_messages call."""

    action: str = Field(..., description="One of: skip, append, replace")
    message_count: int


class MemoryContextResponse(BaseModel):
    """Episodic memory context injected at the start of an agent turn.

    ``current_episode`` is the rolling summary of THIS SAME thread (empty when
    nothing has been summarized yet). Memory is independent per thread —
    episodes of other conversations are never included.
    """

    current_episode: dict = Field(default_factory=dict)
