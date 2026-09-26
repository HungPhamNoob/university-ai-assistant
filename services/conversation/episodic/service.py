# ============================================
# services/conversation/episodic/service.py
# ============================================
"""
Orchestration for episodic memory (INDEPENDENT PER THREAD — reference C/D).

Per-turn flow (driven by the PUT /messages sync endpoint):
    sync_each_turn  -> advances the EpisodeSummary row's message counts
    maybe_summarize -> when enough new messages accumulated, runs the rolling
                       summarizer (bounded wait) over THIS thread's own old
                       messages
    build_memory_context -> the current thread's episode (nothing else)

The SQL row is canonical and the ONLY store — there is no vector mirror and
no cross-thread retrieval: memory of one conversation never leaks into
another. The LLM summarizer is optional and degrades gracefully so a sync
can never break because of it.
"""

import asyncio
import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import HumanMessage, SystemMessage

from ..models import utc_now
from ..repository import ConversationRepository
from ..settings import settings
from .prompt import EPISODE_SUMMARY_PROMPT, parse_episode_json
from .retriever import EpisodicRetriever, serialize_episode

logger = logging.getLogger(__name__)


def compute_episode_digest(
    previous_digest: str | None,
    messages: list[dict],
    version: int,
) -> str:
    """
    Chained sha256 digest over the previous digest, version and new messages.

    Chaining the previous digest makes the hash incremental: an unchanged
    message delta produces an unchanged digest, which lets ``maybe_summarize``
    skip re-summarizing identical content.

    Args:
        previous_digest: The episode's current source_digest (or None/"").
        messages: New message dicts with ``role`` and ``content`` keys.
        version: The summarization version.

    Returns:
        A 64-char hex digest.
    """
    canonical = json.dumps(
        {
            "previous_digest": previous_digest or "",
            "version": version,
            "messages": [
                {
                    "role": str(item.get("role", "user")),
                    "content": str(item.get("content", "")),
                }
                for item in messages
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def should_summarize(unsummarized: int, threshold: int, force: bool) -> bool:
    """
    Decide whether the rolling summarizer should run.

    Args:
        unsummarized: Count of messages not yet folded into a summary.
        threshold: Minimum unsummarized messages before summarizing.
        force: When True, bypass the threshold.

    Returns:
        True when summarization should proceed.
    """
    if force:
        return True
    return unsummarized >= threshold


def _string_list(value: object) -> list[str]:
    """Coerce an LLM-provided value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_summary(parsed: dict) -> dict:
    """Shape a parsed LLM summary dict into safe, typed episode fields."""
    outcome = parsed.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    status = outcome.get("status", "in_progress")
    if status not in ("in_progress", "completed", "cancelled", "failed"):
        status = "in_progress"
    score = outcome.get("score", 0.0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    return {
        "title": str(parsed.get("title", ""))[:240],
        "context": str(parsed.get("context", "")),
        "summary": str(parsed.get("summary", "")),
        "actions": _string_list(parsed.get("actions")),
        "outcome": {
            "status": status,
            "summary": str(outcome.get("summary", "")),
            "score": score,
        },
        "errors": _string_list(parsed.get("errors")),
        "user_corrections": _string_list(parsed.get("user_corrections")),
        "lessons_learned": _string_list(parsed.get("lessons_learned")),
        "open_loops": _string_list(parsed.get("open_loops")),
        "agents_involved": _string_list(parsed.get("agents_involved")),
    }


class EpisodicService:
    """Public API for one canonical rolling episode per user/thread."""

    def __init__(
        self,
        repository: ConversationRepository,
        retriever: EpisodicRetriever,
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        # Single-worker executor for the blocking LLM call (bounded wait).
        self._executor = ThreadPoolExecutor(max_workers=1)
        # Separate executor for USER-TRIGGERED (force) summarization so a
        # long force job never queues behind (or blocks) the per-turn
        # rolling summarizer of live conversations.
        self._force_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="episodic-force"
        )
        self._llm = None
        self._llm_lock = threading.Lock()

    # ---- lifecycle hooks ---------------------------------------------------

    async def sync_each_turn(
        self,
        conversation_id: str,
        user_id: str,
        messages: list[dict],
    ) -> None:
        """
        Record the current message count on the canonical episode row.

        Args:
            conversation_id: The thread (== conversation) id.
            user_id: Owner of the thread.
            messages: Current full message list the agent just synced.
        """
        total = len(messages)
        episode = await self._repository.get_episode(user_id, conversation_id)
        if episode is None:
            # Chỉ episode ĐÃ summarize mới tồn tại trong Postgres: conversation
            # chưa summarize thì KHÔNG tạo row. Ngưỡng 20 tin được tính trên
            # toàn bộ message list khi row chưa tồn tại (xem maybe_summarize).
            return
        shrink_fields: dict = {}
        if total < episode.last_summarized_message_count:
            # History vừa bị REPLACE ngắn lại (sync semantics: khác prefix → replace).
            # High-watermark cũ lớn hơn total sẽ khiến delta messages[last:] luôn
            # rỗng → summarizer kẹt vĩnh viễn. Clamp về total để vòng rolling
            # tiếp tục từ lịch sử mới (summary cũ vẫn được kế thừa qua digest).
            shrink_fields["last_summarized_message_count"] = total
            shrink_fields["last_summarized_position"] = max(-1, total - 1)
            logger.info(
                "event=episode_watermark_clamped user_id=%s thread_id=%s total=%d previous=%d",
                user_id,
                conversation_id,
                total,
                episode.last_summarized_message_count,
            )
        await self._repository.upsert_episode(
            user_id=user_id,
            thread_id=conversation_id,
            total_message_count=total,
            **shrink_fields,
        )

    async def current_episode(self, user_id: str, thread_id: str) -> dict:
        """
        Serialized episode of the thread ({} when not summarized yet).

        Exposed for the user-triggered "summarize now" flow so the API can
        report the fresh episode back to the UI.
        """
        return await self._retriever.get_current_episode(user_id, thread_id)

    async def maybe_summarize(
        self,
        user_id: str,
        thread_id: str,
        force: bool = False,
    ) -> None:
        """
        Run the rolling summarizer when enough new messages accumulated.

        Args:
            user_id: Owner of the thread.
            thread_id: The conversation id.
            force: When True, summarize regardless of the threshold.
        """
        episode = await self._repository.get_episode(user_id, thread_id)
        messages = await self._repository.list_messages(thread_id)
        total = len(messages)
        if episode is None:
            # Chưa summarize lần nào: baseline trống, toàn bộ message list là
            # "new" (row chỉ được tạo SAU khi LLM summarize thành công).
            last_summarized = 0
            base_digest = ""
            previous: dict = {}
        else:
            last_summarized = episode.last_summarized_message_count
            base_digest = episode.source_digest
            previous = serialize_episode(episode)
        new_messages = messages[last_summarized:]
        if not new_messages:
            return

        unsummarized = total - last_summarized
        if not should_summarize(
            unsummarized, settings.EPISODIC_MESSAGE_THRESHOLD, force
        ):
            logger.info(
                "event=episode_summary_skipped user_id=%s thread_id=%s unsummarized=%d threshold=%d",
                user_id,
                thread_id,
                unsummarized,
                settings.EPISODIC_MESSAGE_THRESHOLD,
            )
            return

        normalized_new = [
            {"role": item.role, "content": item.content} for item in new_messages
        ]
        digest = compute_episode_digest(
            base_digest,
            normalized_new,
            settings.EPISODIC_SUMMARIZATION_VERSION,
        )
        if episode is not None and digest == episode.source_digest:
            logger.info(
                "event=episode_summary_digest_unchanged user_id=%s thread_id=%s",
                user_id,
                thread_id,
            )
            return

        # Force jobs run on their own executor: a user-triggered summarize
        # must not stall the per-turn rolling summarizer of other requests.
        executor = self._force_executor if force else self._executor
        future = executor.submit(self._summarize_sync, previous, normalized_new)
        try:
            # KHÔNG dùng future.result() trong coroutine: đó là blocking call
            # sẽ đóng băng event loop của service suốt lúc LLM chạy (mọi
            # request khác — load messages, status... — treo theo). wrap_future
            # + wait_for giữ nguyên timeout mà không chặn loop.
            summary = await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=settings.EPISODIC_LLM_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            future.cancel()
            await self._set_summarization_error(
                user_id,
                thread_id,
                f"Episodic summarization exceeded {settings.EPISODIC_LLM_TIMEOUT_SECONDS:g}s.",
            )
            return
        except Exception as error:  # noqa: BLE001 - never break the sync
            await self._set_summarization_error(user_id, thread_id, str(error)[:2048])
            return

        now = utc_now()
        await self._repository.upsert_episode(
            user_id=user_id,
            thread_id=thread_id,
            title=summary["title"],
            context=summary["context"],
            summary=summary["summary"],
            actions=summary["actions"],
            outcome=summary["outcome"],
            errors=summary["errors"],
            user_corrections=summary["user_corrections"],
            lessons_learned=summary["lessons_learned"],
            open_loops=summary["open_loops"],
            agents_involved=summary["agents_involved"],
            total_message_count=total,
            last_summarized_position=total - 1,
            last_summarized_message_count=total,
            source_digest=digest,
            summarization_version=settings.EPISODIC_SUMMARIZATION_VERSION,
            status="active",
            summarized_at=now,
            finalized_at=None,
            summarization_error="",
        )
        logger.info(
            "event=episode_summarized user_id=%s thread_id=%s total=%d",
            user_id,
            thread_id,
            total,
        )

    async def build_memory_context(
        self, user_id: str, thread_id: str, query: str
    ) -> dict:
        """
        Build the memory context injected at the start of an agent turn.

        Independent-thread policy (reference C/D): ONLY the current thread's
        own rolling episode is returned. Episodes of other conversations are
        never injected — `query` is accepted for interface stability but no
        similarity search happens anymore.

        Args:
            user_id: Owner of the thread.
            thread_id: The conversation id.
            query: The current user query (unused — kept for API stability).

        Returns:
            A dict matching MemoryContextResponse: {"current_episode": dict}.
        """
        if not settings.EPISODIC_ENABLED:
            return {"current_episode": {}}
        current = await self._retriever.get_current_episode(user_id, thread_id)
        return {"current_episode": current}

    # ---- internals ----------------------------------------------------------

    def _get_llm(self):
        """Build (once) the LLM used by the episodic summarizer, or None."""
        if self._llm is None:
            with self._llm_lock:
                if self._llm is None:
                    if not settings.API_KEY:
                        return None
                    try:
                        from langchain_openai import ChatOpenAI

                        self._llm = ChatOpenAI(
                            model=settings.LLM_MODEL,
                            api_key=settings.API_KEY,
                            base_url=settings.BASE_URL,
                            temperature=0.0,
                            timeout=float(settings.EPISODIC_LLM_TIMEOUT_SECONDS),
                            max_retries=1,
                        )
                    except Exception as error:  # noqa: BLE001 - optional dependency
                        logger.warning("event=episode_llm_unavailable error=%s", error)
                        return None
        return self._llm

    def _summarize_sync(self, previous: dict, new_messages: list[dict]) -> dict:
        """Blocking LLM call (runs inside the executor worker thread)."""
        llm = self._get_llm()
        if llm is None:
            raise RuntimeError(
                "Episodic summarizer LLM unavailable (no API key configured)"
            )
        payload = json.dumps(
            {"previous_episode": previous, "new_messages": new_messages},
            ensure_ascii=False,
            default=str,
        )[: settings.EPISODIC_MAX_PROMPT_CHARS]
        response = llm.invoke(
            [
                SystemMessage(content=EPISODE_SUMMARY_PROMPT),
                HumanMessage(content=payload),
            ]
        )
        parsed = parse_episode_json(str(response.content))
        if parsed is None:
            raise ValueError("Episodic summarizer returned non-JSON output")
        return _normalize_summary(parsed)

    async def _set_summarization_error(
        self, user_id: str, thread_id: str, error: str
    ) -> None:
        """Persist a summarization failure without raising."""
        await self._repository.upsert_episode(
            user_id=user_id,
            thread_id=thread_id,
            status="error",
            summarization_error=error[:2048],
        )
        logger.warning(
            "event=episode_summary_failed user_id=%s thread_id=%s error=%s",
            user_id,
            thread_id,
            error,
        )
