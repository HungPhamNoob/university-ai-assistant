"""Focused tests for the UET illustrative room catalog."""

from datetime import datetime, timedelta

import pytest

from services.booking.rules import ROOMS, validate_booking_basics


def future_window() -> tuple[datetime, datetime]:
    """Return a stable future one-hour window."""
    start = datetime.now() + timedelta(days=2)
    return start, start + timedelta(hours=1)


def test_room_catalog_matches_uet_reference() -> None:
    """The operational catalog preserves all 24 records and key attributes."""
    assert len(ROOMS) == 24
    assert ROOMS["GD3-402"] == {
        "site_code": "GD3",
        "site_name": "Giảng đường 3",
        "room_type": "MEETING",
        "capacity": 16,
        "status": "ACTIVE",
        "equipment": ["video conference"],
        "address": None,
        "source_status": "illustrative",
    }
    assert ROOMS["HL-A101"]["capacity"] == 150
    assert ROOMS["HL-A101"]["status"] == "ACTIVE"


@pytest.mark.parametrize("room", ["GD3-302", "KM-301", "HL-B201", "HL-B202"])
def test_non_active_rooms_cannot_be_booked(room: str) -> None:
    """Maintenance and restricted records remain discoverable but not bookable."""
    start, end = future_window()
    with pytest.raises(ValueError, match="not available for normal booking"):
        validate_booking_basics(room, start, end)


def test_active_room_is_bookable() -> None:
    """An active room with a valid future window passes catalog validation."""
    start, end = future_window()
    validate_booking_basics("HL-C201", start, end)
