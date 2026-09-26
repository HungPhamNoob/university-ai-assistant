# ============================================
# services/booking/rules.py
# ============================================
"""
Business rules of the Booking service.

Kept separate from the CRUD service so the validation logic is testable on
its own: meeting room catalog, time-window checks and double-booking
(overlap) detection against the real database.
"""

from datetime import datetime
from typing import TypedDict

from .models import Booking
from .repository import BookingRepository
from .schemas import BookingStatus


class RoomDetails(TypedDict):
    """Operational fields exposed by the illustrative UET room registry."""

    site_code: str
    site_name: str
    room_type: str
    capacity: int
    status: str
    equipment: list[str]
    address: None
    source_status: str


# Illustrative records from UET_HR.pdf section C3. These are intentionally
# sample data for development and must be synchronized with an authoritative
# facility system before production use.
ROOMS: dict[str, RoomDetails] = {
    "GD3-101": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "LECTURE",
        "capacity": 120,
        "status": "ACTIVE",
        "equipment": ["projector", "microphone", "capture"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-102": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "LECTURE",
        "capacity": 90,
        "status": "ACTIVE",
        "equipment": ["projector", "speakers"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-201": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "LECTURE",
        "capacity": 80,
        "status": "ACTIVE",
        "equipment": ["projector", "display"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-202": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "SEMINAR",
        "capacity": 48,
        "status": "ACTIVE",
        "equipment": ["display", "flexible seating"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-301": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "COMPUTER_LAB",
        "capacity": 42,
        "status": "ACTIVE",
        "equipment": ["42 workstations", "wired network"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-302": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "COMPUTER_LAB",
        "capacity": 36,
        "status": "MAINTENANCE",
        "equipment": ["36 workstations", "lab VLAN"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-401": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "PROJECT",
        "capacity": 28,
        "status": "ACTIVE",
        "equipment": ["display", "whiteboard"],
        "address": None,
        "source_status": "illustrative",
    },
    "GD3-402": {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "MEETING",
        "capacity": 16,
        "status": "ACTIVE",
        "equipment": ["video conference"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-101": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "LECTURE",
        "capacity": 100,
        "status": "ACTIVE",
        "equipment": ["projector", "microphone"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-102": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "LECTURE",
        "capacity": 70,
        "status": "ACTIVE",
        "equipment": ["projector", "speakers"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-201": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "SEMINAR",
        "capacity": 40,
        "status": "ACTIVE",
        "equipment": ["display", "movable desks"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-202": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "COMPUTER_LAB",
        "capacity": 40,
        "status": "ACTIVE",
        "equipment": ["40 workstations", "wired network"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-301": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "ELECTRONICS_LAB",
        "capacity": 32,
        "status": "RESTRICTED",
        "equipment": ["oscilloscopes", "bench supplies"],
        "address": None,
        "source_status": "illustrative",
    },
    "KM-302": {
        "site_code": "KM",
        "site_name": "Khu giảng đường Kiều Mai",
        "room_type": "PROJECT",
        "capacity": 24,
        "status": "ACTIVE",
        "equipment": ["whiteboards", "team tables"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-A101": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "LECTURE",
        "capacity": 150,
        "status": "ACTIVE",
        "equipment": ["projector", "microphone", "capture"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-A102": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "LECTURE",
        "capacity": 120,
        "status": "ACTIVE",
        "equipment": ["dual display", "microphone"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-A201": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "SEMINAR",
        "capacity": 54,
        "status": "ACTIVE",
        "equipment": ["display", "flexible seating"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-A301": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "COMPUTER_LAB",
        "capacity": 48,
        "status": "ACTIVE",
        "equipment": ["48 workstations", "lab network"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-B101": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "ELECTRONICS_LAB",
        "capacity": 36,
        "status": "ACTIVE",
        "equipment": ["bench supplies", "instruments"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-B201": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "ROBOTICS_LAB",
        "capacity": 30,
        "status": "RESTRICTED",
        "equipment": ["robot platforms", "safety zone"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-B202": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "ROBOTICS_LAB",
        "capacity": 24,
        "status": "MAINTENANCE",
        "equipment": ["automation cells"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-C101": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "PROJECT",
        "capacity": 36,
        "status": "ACTIVE",
        "equipment": ["team tables", "display"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-C102": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "PROJECT",
        "capacity": 24,
        "status": "ACTIVE",
        "equipment": ["whiteboards", "storage"],
        "address": None,
        "source_status": "illustrative",
    },
    "HL-C201": {
        "site_code": "HL",
        "site_name": "Cơ sở Hòa Lạc",
        "room_type": "MEETING",
        "capacity": 18,
        "status": "ACTIVE",
        "equipment": ["video conference"],
        "address": None,
        "source_status": "illustrative",
    },
}


class BookingConflictError(Exception):
    """Raised when the requested room is already booked for that time slot."""


class BookingNotFoundError(Exception):
    """Raised when a booking id does not exist."""


def room_exists(room: str) -> bool:
    """
    Check that a room name belongs to the catalog.

    Args:
        room: Room name provided by the caller.

    Returns:
        True when the room is bookable.
    """
    return room in ROOMS


def time_window_is_valid(start_at: datetime, end_at: datetime) -> bool:
    """
    Check that a time window is usable (end strictly after start).

    Args:
        start_at: Requested start time.
        end_at: Requested end time.

    Returns:
        True when the window is valid.
    """
    return end_at > start_at


def overlaps(
    start_at: datetime, end_at: datetime, other_start: datetime, other_end: datetime
) -> bool:
    """
    Decide whether two time intervals overlap.

    Two intervals overlap when existing.start < new.end and existing.end > new.start.

    Args:
        start_at: Start of the first interval.
        end_at: End of the first interval.
        other_start: Start of the second interval.
        other_end: End of the second interval.

    Returns:
        True when the intervals collide.
    """
    return other_start < end_at and other_end > start_at


def validate_booking_basics(room: str, start_at: datetime, end_at: datetime) -> None:
    """
    Validate the room catalog and the time window of a booking request.

    Args:
        room: Room name to book.
        start_at: Requested start time.
        end_at: Requested end time.

    Raises:
        ValueError: When the room is unknown, the window is empty or in the past.
    """
    if not room_exists(room):
        raise ValueError(f"Unknown room '{room}'. Available rooms: {', '.join(ROOMS)}")
    room_status = ROOMS[room]["status"]
    if room_status != "ACTIVE":
        raise ValueError(
            f"Room '{room}' is not available for normal booking because its "
            f"status is {room_status}."
        )
    if not time_window_is_valid(start_at, end_at):
        raise ValueError("end_at must be after start_at")
    if start_at <= datetime.now():
        raise ValueError("start_at is in the past: bookings must start in the future")


def describe_conflict(conflict: Booking, room: str, user_id: str | None = None) -> str:
    """
    Build a human-readable conflict message.

    When the blocking booking belongs to the requesting user the message names
    the booking id so the assistant can offer to cancel it first; otherwise it
    states that another user occupies the slot.

    Args:
        conflict: The confirmed booking that blocks the requested slot.
        room: Room name that was requested.
        user_id: Requesting user, used for the own-vs-foreign distinction.

    Returns:
        The conflict explanation string.
    """
    window = f"{conflict.start_at:%Y-%m-%d %H:%M} to {conflict.end_at:%Y-%m-%d %H:%M}"
    if user_id is not None and conflict.user_id == user_id:
        return (
            f"Room {room} is already booked from {window} by your own booking "
            f"{conflict.booking_id} (purpose: '{conflict.purpose}'). "
            f"That booking must be cancelled first before this slot can be rebooked."
        )
    return (
        f"Room {room} is already booked from {window} by another user. "
        f"Choose a different time or a different room."
    )


async def validate_new_booking(
    repository: BookingRepository,
    room: str,
    start_at: datetime,
    end_at: datetime,
    user_id: str | None = None,
) -> None:
    """
    Validate a booking creation request against all business rules.

    Args:
        repository: Data access object used for the overlap query.
        room: Room name to book.
        start_at: Requested start time.
        end_at: Requested end time.
        user_id: Requesting user, used for the own-vs-foreign conflict message.

    Raises:
        ValueError: When the room is unknown or the time window is invalid.
        BookingConflictError: When the slot overlaps an existing confirmed booking.
    """
    validate_booking_basics(room, start_at, end_at)

    conflict = await repository.find_conflict(room, start_at, end_at)
    if conflict is not None:
        raise BookingConflictError(describe_conflict(conflict, room, user_id))


async def validate_reschedule(
    repository: BookingRepository,
    booking: Booking,
    new_start: datetime,
    new_end: datetime,
) -> None:
    """
    Validate a time change of an existing booking.

    Args:
        repository: Data access object used for the overlap query.
        booking: Booking being updated.
        new_start: New start time.
        new_end: New end time.

    Raises:
        ValueError: When the new time window is invalid.
        BookingConflictError: When the new slot overlaps another booking.
    """
    if not time_window_is_valid(new_start, new_end):
        raise ValueError("end_at must be after start_at")
    if new_start <= datetime.now():
        raise ValueError("start_at is in the past: bookings must start in the future")

    conflict: Booking | None = await repository.find_conflict(
        booking.room, new_start, new_end
    )
    if conflict is not None and conflict.booking_id != booking.booking_id:
        raise BookingConflictError(
            f"Room {booking.room} is already booked in the requested slot"
        )


def can_cancel(booking: Booking) -> bool:
    """
    Check whether a booking can still be cancelled.

    Args:
        booking: Booking to inspect.

    Returns:
        True when the booking is not cancelled yet.
    """
    return booking.status != BookingStatus.CANCELLED.value
