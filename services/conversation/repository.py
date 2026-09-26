# ============================================
# services/conversation/repository.py
# ============================================
"""
Data access layer for conversations and messages.
Every method performs real SQL against Postgres.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Conversation, EpisodeSummary, Message


class ConversationRepository:
    """Repository encapsulating all conversation persistence operations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        Args:
            session_factory: Factory producing async database sessions.
        """
        self._session_factory = session_factory

    async def create(self, conversation: Conversation) -> Conversation:
        """
        Insert a new conversation row.

        Args:
            conversation: Conversation entity to persist.

        Returns:
            The persisted conversation entity.
        """
        async with self._session_factory() as session:
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
            return conversation

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        """
        Fetch one conversation by id (without messages).

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            The conversation entity, or None when not found.
        """
        async with self._session_factory() as session:
            return await session.get(Conversation, conversation_id)

    async def get_or_create(
        self, conversation_id: str, user_id: str, title: str
    ) -> Conversation:
        """
        Fetch a conversation by id, creating it when it does not exist yet.

        This makes the internal sync endpoint idempotent: the agent can sync a
        thread before any explicit conversation creation happened.

        Args:
            conversation_id: Unique conversation identifier.
            user_id: Owner used when the row must be created.
            title: Title used when the row must be created.

        Returns:
            The existing or newly created conversation entity.
        """
        existing = await self.get_by_id(conversation_id)
        if existing is not None:
            return existing
        conversation = Conversation(
            conversation_id=conversation_id, user_id=user_id, title=title
        )
        return await self.create(conversation)

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        """
        List all conversations of one user, newest activity first.

        Args:
            user_id: Owner of the conversations.

        Returns:
            List of conversation entities.
        """
        async with self._session_factory() as session:
            statement = (
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def delete(self, conversation_id: str) -> bool:
        """
        Delete one conversation (messages removed via cascade delete-orphan).

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            True when a row was deleted, False when not found.
        """
        async with self._session_factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            await session.delete(conversation)
            await session.commit()
            return True

    async def list_messages(self, conversation_id: str) -> list[Message]:
        """
        Fetch all messages of one conversation in chronological order.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            List of message entities.
        """
        async with self._session_factory() as session:
            statement = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc(), Message.message_id.asc())
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def append_messages(
        self, conversation_id: str, messages: list[dict]
    ) -> list[Message]:
        """
        Append messages to a conversation.

        Args:
            conversation_id: Unique conversation identifier.
            messages: List of {"role": str, "content": str} dicts.

        Returns:
            The newly inserted message entities.
        """
        async with self._session_factory() as session:
            entities = [
                Message(
                    conversation_id=conversation_id,
                    role=item["role"],
                    content=item["content"],
                )
                for item in messages
            ]
            session.add_all(entities)
            await session.commit()
            for entity in entities:
                await session.refresh(entity)
            return entities

    async def replace_messages(
        self, conversation_id: str, messages: list[dict]
    ) -> list[Message]:
        """
        Replace all messages of a conversation with the given list.

        Args:
            conversation_id: Unique conversation identifier.
            messages: List of {"role": str, "content": str} dicts.

        Returns:
            The new list of message entities.
        """
        async with self._session_factory() as session:
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            entities = [
                Message(
                    conversation_id=conversation_id,
                    role=item["role"],
                    content=item["content"],
                )
                for item in messages
            ]
            session.add_all(entities)
            await session.commit()
            for entity in entities:
                await session.refresh(entity)
            return entities

    async def get_episode(self, user_id: str, thread_id: str) -> EpisodeSummary | None:
        """
        Fetch the canonical episode summary for one (user, thread).

        Args:
            user_id: Owner of the episode.
            thread_id: The conversation id.

        Returns:
            The EpisodeSummary row, or None when not found.
        """
        async with self._session_factory() as session:
            statement = select(EpisodeSummary).where(
                EpisodeSummary.user_id == user_id,
                EpisodeSummary.thread_id == thread_id,
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def upsert_episode(
        self, user_id: str, thread_id: str, **fields
    ) -> EpisodeSummary:
        """
        Create or update the canonical episode summary for one (user, thread).

        Args:
            user_id: Owner of the episode.
            thread_id: The conversation id.
            **fields: EpisodeSummary column values to apply.

        Returns:
            The persisted EpisodeSummary row.
        """
        async with self._session_factory() as session:
            statement = select(EpisodeSummary).where(
                EpisodeSummary.user_id == user_id,
                EpisodeSummary.thread_id == thread_id,
            )
            result = await session.execute(statement)
            episode = result.scalar_one_or_none()
            if episode is None:
                episode = EpisodeSummary(user_id=user_id, thread_id=thread_id, **fields)
                session.add(episode)
            else:
                for field, value in fields.items():
                    setattr(episode, field, value)
            await session.commit()
            await session.refresh(episode)
            return episode
