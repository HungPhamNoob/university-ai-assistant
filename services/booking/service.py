# ============================================
# services/booking/service.py
# ============================================
"""
Business logic of the Booking service.

Every operation runs against the real Postgres database through the
repository. All validation (room catalog, time window, double-booking)
is delegated to rules.py before any write happens.
"""

import logging
from copy import deepcopy
from datetime import datetime

from .models import Booking
from .repository import BookingRepository
from .rules import (
    ROOMS,
    BookingNotFoundError,
    can_cancel,
    validate_booking_basics,
    validate_new_booking,
    validate_reschedule,
)
from .schemas import BookingCreate, BookingResponse, BookingStatus, BookingUpdate

logger = logging.getLogger(__name__)


class BookingService:
    """Use-case layer orchestrating booking CRUD and business rules."""

    def __init__(self, repository: BookingRepository):
        """
        Args:
            repository: Data access object for bookings.
        """
        self._repository = repository

    def list_rooms(self) -> dict[str, dict[str, object]]:
        """
        Return the meeting room catalog.

        Returns:
        Mapping of room code to its operational catalog fields.
        """
        return deepcopy(ROOMS)

    async def create_booking(self, data: BookingCreate) -> BookingResponse:
        """
        Create a new booking after validating room and time slot.

        Args:
            data: Validated booking creation payload.

        Returns:
            The persisted booking.

        Raises:
            ValueError: When the room is unknown or the time window is invalid.
            BookingConflictError: When the slot overlaps an existing booking.
        """
        room = data.room.strip()
        await validate_new_booking(
            self._repository, room, data.start_at, data.end_at, user_id=data.user_id
        )

        booking = Booking(
            user_id=data.user_id,
            room=room,
            purpose=data.purpose.strip(),
            start_at=data.start_at,
            end_at=data.end_at,
            status=BookingStatus.CONFIRMED.value,
        )
        saved = await self._repository.create(booking)
        logger.info(
            "Booking created id=%s room=%s user=%s",
            saved.booking_id,
            room,
            data.user_id,
        )
        return BookingResponse.model_validate(saved)

    async def check_availability(
        self, room: str, start_at: datetime, end_at: datetime, user_id: str
    ) -> dict[str, object]:
        """
        Read-only availability probe for a room + time slot.

        Args:
            room: Room name to check.
            start_at: Requested start time.
            end_at: Requested end time.
            user_id: Requesting user (own-vs-foreign conflict detection).

        Returns:
            Dict with 'available'=True when the slot is free; when occupied
            'available'=False plus 'own_conflict' and the blocking booking's
            details under 'conflict'.

        Raises:
            ValueError: When the room is unknown or the time window is invalid.
        """
        room = room.strip()
        validate_booking_basics(room, start_at, end_at)

        conflict = await self._repository.find_conflict(room, start_at, end_at)
        if conflict is None:
            return {"available": True, "own_conflict": False, "conflict": None}
        return {
            "available": False,
            "own_conflict": conflict.user_id == user_id,
            "conflict": {
                "booking_id": conflict.booking_id,
                "room": conflict.room,
                "start_at": conflict.start_at.isoformat(),
                "end_at": conflict.end_at.isoformat(),
                "purpose": conflict.purpose,
            },
        }

    async def get_booking(
        self, booking_id: str, user_id: str | None = None
    ) -> BookingResponse:
        """
        Fetch one booking by id. Only the owner may read it when a user is given.

        Args:
            booking_id: Unique booking identifier.
            user_id: Optional owner check; rejects foreign bookings when set.

        Returns:
            The booking payload.

        Raises:
            BookingNotFoundError: When the id does not exist.
            PermissionError: When the booking belongs to another user.
        """
        booking = await self._require(booking_id)
        if user_id is not None and booking.user_id != user_id:
            raise PermissionError("This booking belongs to another user")
        return BookingResponse.model_validate(booking)

    async def list_bookings(self, user_id: str) -> list[BookingResponse]:
        """
        List all bookings of one user, newest first.

        Args:
            user_id: Owner of the bookings.

        Returns:
            List of booking payloads.
        """
        bookings = await self._repository.list_by_user(user_id)
        return [BookingResponse.model_validate(item) for item in bookings]

    async def update_booking(
        self, booking_id: str, data: BookingUpdate, user_id: str | None = None
    ) -> BookingResponse:
        """
        Partially update one booking (purpose / times / status). Only the
        owner may reschedule it when a user is given.

        Args:
            booking_id: Unique booking identifier.
            data: Fields to update; None values are ignored.
            user_id: Optional owner check; rejects foreign bookings when set.

        Returns:
            The updated booking payload.

        Raises:
            BookingNotFoundError: When the id does not exist.
            PermissionError: When the booking belongs to another user.
            BookingConflictError: When the new time slot overlaps another booking.
            ValueError: When the resulting time window is invalid.
        """
        booking = await self._require(booking_id)
        if user_id is not None and booking.user_id != user_id:
            raise PermissionError("This booking belongs to another user")

        new_start = data.start_at or booking.start_at
        new_end = data.end_at or booking.end_at
        if data.start_at is not None or data.end_at is not None:
            await validate_reschedule(self._repository, booking, new_start, new_end)

        fields = {
            column: value
            for column, value in {
                "purpose": data.purpose,
                "start_at": data.start_at,
                "end_at": data.end_at,
                "status": data.status,
            }.items()
            if value is not None
        }
        updated = await self._repository.update_fields(booking_id, fields)
        logger.info("Booking updated id=%s fields=%s", booking_id, list(fields))
        return BookingResponse.model_validate(updated)

    async def cancel_booking(
        self, booking_id: str, user_id: str | None = None
    ) -> BookingResponse:
        """
        Cancel one booking. Only non-cancelled bookings can be cancelled.

        Args:
            booking_id: Unique booking identifier.
            user_id: Optional owner check; rejects foreign bookings when set.

        Returns:
            The cancelled booking payload.

        Raises:
            BookingNotFoundError: When the id does not exist.
            PermissionError: When the booking belongs to another user.
            ValueError: When the booking is already cancelled.
        """
        booking = await self._require(booking_id)
        if user_id is not None and booking.user_id != user_id:
            raise PermissionError("This booking belongs to another user")
        if not can_cancel(booking):
            raise ValueError(f"Booking '{booking_id}' is already cancelled")

        updated = await self._repository.update_fields(
            booking_id, {"status": BookingStatus.CANCELLED.value}
        )
        logger.info("Booking cancelled id=%s", booking_id)
        return BookingResponse.model_validate(updated)

    async def _require(self, booking_id: str) -> Booking:
        """
        Fetch a booking or raise BookingNotFoundError.

        Args:
            booking_id: Unique booking identifier.

        Returns:
            The booking entity.

        Raises:
            BookingNotFoundError: When the id does not exist.
        """
        booking = await self._repository.get_by_id(booking_id)
        if booking is None:
            raise BookingNotFoundError(f"Booking '{booking_id}' not found")
        return booking
