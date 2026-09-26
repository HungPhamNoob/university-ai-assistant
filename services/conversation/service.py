# ============================================
# services/conversation/service.py
# ============================================
"""
Business logic of the Conversation service.

Implements conversation CRUD and coordinates message synchronization
(the skip/append/replace comparison itself lives in message_sync.py).
Read endpoints use the optional Redis cache; writes invalidate it.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from .cache import RedisCacheService
from .message_sync import sync_messages
from .models import Conversation
from .repository import ConversationRepository
from .schemas import (
    ConversationSummary,
    CreateConversationRequest,
    MessageDTO,
    SyncMessagesRequest,
    SyncResult,
)
from .settings import settings

logger = logging.getLogger(__name__)


class ConversationNotFoundError(Exception):
    """Raised when a conversation id does not exist."""


class ConversationService:
    """Use-case layer orchestrating conversations, messages and summaries."""

    def __init__(
        self,
        repository: ConversationRepository,
        cache: RedisCacheService,
        episodic=None,
    ):
        """
        Args:
            repository: Data access object for conversations/messages.
            cache: Optional Redis cache (graceful no-op when disabled).
            episodic: Optional EpisodicService used for per-turn memory upkeep.
        """
        self._repository = repository
        self._cache = cache
        self._episodic = episodic
        # In-memory registry of user-triggered summarize jobs, keyed by
        # conversation id. Jobs run as background asyncio tasks so the HTTP
        # request returns immediately and the app stays fully responsive
        # (rendering messages, chatting...) while the LLM summary runs.
        self._summarize_jobs: dict[str, dict[str, Any]] = {}

    async def create_conversation(
        self, data: CreateConversationRequest
    ) -> ConversationSummary:
        """
        Create a new empty conversation.

        Args:
            data: Creation payload (user_id, title).

        Returns:
            The persisted conversation header.
        """
        conversation = Conversation(
            user_id=data.user_id, title=data.title.strip() or "New conversation"
        )
        saved = await self._repository.create(conversation)
        self._cache.delete_pattern(f"conversation:user:{saved.user_id}:*")
        logger.info(
            "Conversation created id=%s user=%s", saved.conversation_id, saved.user_id
        )
        return ConversationSummary.model_validate(saved)

    async def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        """
        List all conversations of one user (cache-backed when Redis is on).

        Args:
            user_id: Owner of the conversations.

        Returns:
            List of conversation headers, newest activity first.
        """
        cache_key = f"conversation:user:{user_id}:list"
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            return [ConversationSummary.model_validate(item) for item in cached]

        conversations = await self._repository.list_by_user(user_id)
        summaries = [ConversationSummary.model_validate(item) for item in conversations]
        self._cache.set_json(
            cache_key, [item.model_dump(mode="json") for item in summaries]
        )
        return summaries

    async def get_conversation(self, conversation_id: str) -> ConversationSummary:
        """
        Fetch one conversation header (cache-backed when Redis is on).

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            The conversation header.

        Raises:
            ConversationNotFoundError: When the id does not exist.
        """
        cache_key = f"conversation:{conversation_id}:detail"
        cached = self._cache.get_json(cache_key)
        if cached is not None:
            return ConversationSummary.model_validate(cached)

        conversation = await self._require(conversation_id)
        summary = ConversationSummary.model_validate(conversation)
        self._cache.set_json(cache_key, summary.model_dump(mode="json"))
        return summary

    async def require_owner(
        self, conversation_id: str, user_id: str
    ) -> ConversationSummary:
        """
        Fetch one conversation header and enforce ownership.

        Args:
            conversation_id: Unique conversation identifier.
            user_id: Requesting user (trusted X-User-Id from the gateway).

        Returns:
            The conversation header when the user owns it.

        Raises:
            ConversationNotFoundError: When the id does not exist.
            PermissionError: When the conversation belongs to another user.
        """
        header = await self.get_conversation(conversation_id)
        if header.user_id != user_id:
            raise PermissionError("This conversation belongs to another user")
        return header

    async def force_summarize_episode(
        self, conversation_id: str, user_id: str
    ) -> dict[str, Any]:
        """
        Run the episodic summarizer NOW, bypassing the message threshold
        (user-triggered from the UI "Tóm tắt" button).

        Args:
            conversation_id: Conversation to summarize.
            user_id: Owner (enforced).

        Returns:
            Dict with summarized flag, the serialized episode and message
            counts so the caller can show whether the process completed.

        Raises:
            ConversationNotFoundError / PermissionError: ownership checks.
            ValueError: episodic disabled or the conversation has no messages.
        """
        if not settings.EPISODIC_ENABLED or self._episodic is None:
            raise ValueError("Episodic memory đang tắt (EPISODIC_ENABLED=false)")
        await self.require_owner(conversation_id, user_id)

        messages = await self._repository.list_messages(conversation_id)
        if not messages:
            raise ValueError("Cuộc trò chuyện chưa có tin nhắn nào để tóm tắt")

        full = [{"role": item.role, "content": item.content} for item in messages]
        # Đảm bảo episode row tồn tại và watermark khớp lịch sử hiện tại trước
        # khi force summarize (sync_each_turn chỉ ghi đếm, không gọi LLM).
        await self._episodic.sync_each_turn(conversation_id, user_id, full)
        await self._episodic.maybe_summarize(user_id, conversation_id, force=True)

        episode = await self._episodic.current_episode(user_id, conversation_id)
        self._cache.delete_pattern(f"conversation:{conversation_id}:*")
        return {
            "conversation_id": conversation_id,
            "summarized": bool(episode),
            "episode": episode,
            "total_messages": len(full),
        }

    async def start_summarize_job(
        self, conversation_id: str, user_id: str
    ) -> dict[str, Any]:
        """
        Kick off episodic summarization as a BACKGROUND job and return its
        state immediately (the UI polls summarize_job_status for completion).

        Args:
            conversation_id: Conversation to summarize.
            user_id: Owner (enforced).

        Returns:
            The job dict: state in {'running', 'done', 'error'} plus
            started_at / finished_at / episode / total_messages / error.

        Raises:
            ConversationNotFoundError / PermissionError: ownership checks.
            ValueError: episodic disabled or the conversation has no messages.
        """
        if not settings.EPISODIC_ENABLED or self._episodic is None:
            raise ValueError("Episodic memory đang tắt (EPISODIC_ENABLED=false)")
        await self.require_owner(conversation_id, user_id)

        messages = await self._repository.list_messages(conversation_id)
        if not messages:
            raise ValueError("Cuộc trò chuyện chưa có tin nhắn nào để tóm tắt")

        existing = self._summarize_jobs.get(conversation_id)
        if existing is not None and existing.get("state") == "running":
            # Idempotent: a second click joins the running job instead of
            # starting a duplicate LLM call.
            return self._public_job(existing)

        job: dict[str, Any] = {
            "state": "running",
            "conversation_id": conversation_id,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "error": "",
            "episode": {},
            "total_messages": len(messages),
        }
        self._summarize_jobs[conversation_id] = job
        # Keep a reference on the job so the task is never garbage-collected
        # while running.
        job["task"] = asyncio.create_task(
            self._run_summarize_job(conversation_id, user_id)
        )
        return self._public_job(job)

    async def _run_summarize_job(self, conversation_id: str, user_id: str) -> None:
        """
        Background body of a summarize job: runs the force summarization and
        records the outcome on the job registry (never raises).
        """
        job = self._summarize_jobs.get(conversation_id, {})
        try:
            result = await self.force_summarize_episode(conversation_id, user_id)
            job.update(
                {
                    "state": "done",
                    "episode": result.get("episode") or {},
                    "total_messages": result.get("total_messages", 0),
                    "finished_at": datetime.now(UTC).isoformat(),
                    "error": "",
                }
            )
        except Exception as error:  # noqa: BLE001 - record, never crash the loop
            logger.warning(
                "Summarize job failed conversation=%s: %s", conversation_id, error
            )
            job.update(
                {
                    "state": "error",
                    "error": str(error)[:512],
                    "finished_at": datetime.now(UTC).isoformat(),
                }
            )
        logger.info(
            "event=summarize_job conversation_id=%s state=%s",
            conversation_id,
            job.get("state"),
        )

    async def summarize_job_status(
        self, conversation_id: str, user_id: str
    ) -> dict[str, Any]:
        """
        Current state of the summarize job of one conversation (owner only).

        Returns:
            The job dict, or {'state': 'idle'} when no job was started since
            the service booted.
        """
        await self.require_owner(conversation_id, user_id)
        job = self._summarize_jobs.get(conversation_id)
        if job is None:
            return {"state": "idle", "conversation_id": conversation_id}
        return self._public_job(job)

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        """Job view without the internal asyncio task handle."""
        return {key: value for key, value in job.items() if key != "task"}

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete one conversation and all of its messages.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            True when the conversation existed and was deleted.
        """
        conversation = await self._repository.get_by_id(conversation_id)
        deleted = await self._repository.delete(conversation_id)
        if deleted:
            self._cache.delete_pattern(f"conversation:{conversation_id}:*")
            if conversation is not None:
                self._cache.delete_pattern(
                    f"conversation:user:{conversation.user_id}:*"
                )
            logger.info("Conversation deleted id=%s", conversation_id)
        return deleted

    async def list_messages(self, conversation_id: str) -> list[MessageDTO]:
        """
        Fetch all messages of one conversation.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            Messages in chronological order.

        Raises:
            ConversationNotFoundError: When the id does not exist.
        """
        await self._require(conversation_id)
        messages = await self._repository.list_messages(conversation_id)
        return [MessageDTO.model_validate(item) for item in messages]

    async def sync_messages(
        self, conversation_id: str, data: SyncMessagesRequest
    ) -> SyncResult:
        """
        Synchronize the stored messages with the agent thread's messages.

        The conversation is created on the fly when it does not exist yet,
        so the internal sync endpoint stays idempotent. Summarization of THIS
        thread's old messages happens inside the episodic upkeep below
        (threshold-based) — there is no separate summarize flag anymore.

        Args:
            conversation_id: Unique conversation identifier.
            data: Incoming messages from the agent.

        Returns:
            SyncResult describing the action taken and the final count.
        """
        incoming = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in data.messages
        ]

        conversation = await self._repository.get_or_create(
            conversation_id=conversation_id,
            user_id=data.user_id,
            title=data.title.strip() or "Agent conversation",
        )

        action = await sync_messages(self._repository, conversation_id, incoming)

        # Invalidate every cached view of this conversation and its owner list.
        self._cache.delete_pattern(f"conversation:{conversation_id}:*")
        self._cache.delete_pattern(f"conversation:user:{conversation.user_id}:*")

        # Per-turn episodic memory upkeep (best-effort, never breaks the sync).
        if settings.EPISODIC_ENABLED and self._episodic is not None:
            try:
                await self._episodic.sync_each_turn(
                    conversation_id, data.user_id, incoming
                )
                await self._episodic.maybe_summarize(data.user_id, conversation_id)
            except Exception as error:  # noqa: BLE001 - memory is optional
                logger.warning("Episodic sync failed (non-fatal): %s", error)

        return SyncResult(action=action, message_count=len(incoming))

    async def _require(self, conversation_id: str) -> Conversation:
        """
        Fetch a conversation or raise ConversationNotFoundError.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            The conversation entity.

        Raises:
            ConversationNotFoundError: When the id does not exist.
        """
        conversation = await self._repository.get_by_id(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation '{conversation_id}' not found"
            )
        return conversation
