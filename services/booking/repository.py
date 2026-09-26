# ============================================
# services/booking/repository.py
# ============================================
"""
Data access layer for bookings. Every method performs real SQL against Postgres.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Booking
from .schemas import BookingStatus


class BookingRepository:
    """Repository encapsulating all booking persistence operations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        Args:
            session_factory: Factory producing async database sessions.
        """
        self._session_factory = session_factory

    async def create(self, booking: Booking) -> Booking:
        """
        Insert a new booking row.

        Args:
            booking: Booking entity to persist.

        Returns:
            The persisted booking entity.
        """
        async with self._session_factory() as session:
            session.add(booking)
            await session.commit()
            await session.refresh(booking)
            return booking

    async def get_by_id(self, booking_id: str) -> Booking | None:
        """
        Fetch one booking by its id.

        Args:
            booking_id: Unique booking identifier.

        Returns:
            The booking entity, or None when not found.
        """
        async with self._session_factory() as session:
            return await session.get(Booking, booking_id)

    async def list_by_user(self, user_id: str) -> list[Booking]:
        """
        List all bookings of one user, newest first.

        Args:
            user_id: Owner of the bookings.

        Returns:
            List of booking entities.
        """
        async with self._session_factory() as session:
            statement = (
                select(Booking)
                .where(Booking.user_id == user_id)
                .order_by(Booking.created_at.desc())
            )
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def find_conflict(
        self, room: str, start_at: datetime, end_at: datetime
    ) -> Booking | None:
        """
        Find a confirmed booking that overlaps the requested time window.

        Args:
            room: Room name to check.
            start_at: Requested start time.
            end_at: Requested end time.

        Returns:
            The conflicting booking, or None when the slot is free.
        """
        async with self._session_factory() as session:
            statement = (
                select(Booking)
                .where(
                    Booking.room == room,
                    Booking.status == BookingStatus.CONFIRMED.value,
                    Booking.start_at < end_at,
                    Booking.end_at > start_at,
                )
                .limit(1)
            )
            result = await session.execute(statement)
            return result.scalars().first()

    async def update_fields(self, booking_id: str, fields: dict) -> Booking | None:
        """
        Update a set of columns on one booking.

        Args:
            booking_id: Unique booking identifier.
            fields: Mapping of column name to new value.

        Returns:
            The updated booking entity, or None when not found.
        """
        if not fields:
            return await self.get_by_id(booking_id)
        async with self._session_factory() as session:
            booking = await session.get(Booking, booking_id)
            if booking is None:
                return None
            for column, value in fields.items():
                setattr(booking, column, value)
            await session.commit()
            await session.refresh(booking)
            return booking

    async def delete(self, booking_id: str) -> bool:
        """
        Hard-delete one booking row.

        Args:
            booking_id: Unique booking identifier.

        Returns:
            True when a row was deleted, False when not found.
        """
        async with self._session_factory() as session:
            booking = await session.get(Booking, booking_id)
            if booking is None:
                return False
            await session.delete(booking)
            await session.commit()
            return True
