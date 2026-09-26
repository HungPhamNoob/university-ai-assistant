# ============================================
# services/agent/agents/booking.py
# ============================================
"""
Booking Agent: 5 tools backed by the real Booking domain service.

1. list_meeting_rooms — read-only catalog discovery and filtering.
2. book_meeting_room  — HITL interrupt() before the booking is written to Postgres.
3. list_my_bookings   — read-only check of the user's bookings.
4. cancel_booking     — HITL interrupt() before cancelling in Postgres.
5. reschedule_booking — HITL interrupt() before moving a booking to a new time.

Context injection: user_id flows from the parent graph through RunnableConfig.
"""

import json
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ..clients import (
    cancel_booking_db,
    check_booking_availability,
    create_booking_db,
    list_bookings_db,
    list_rooms_db,
    update_booking_db,
)
from .base import create_react_subgraph


class BookingSchema(BaseModel):
    """Arguments required to create a booking."""

    room_name: str = Field(
        description="UET room code, for example 'GD3-402' or 'HL-C201'"
    )
    start_time: str = Field(
        description="Start time in format 'YYYY-MM-DD HH:MM', e.g. '2026-09-01 14:00'"
    )
    duration_minutes: int = Field(
        default=60, description="Meeting duration in minutes, default 60"
    )
    purpose: str = Field(description="Purpose of the meeting")


class RoomCatalogSchema(BaseModel):
    """Optional filters for the UET room registry."""

    min_capacity: int = Field(default=1, ge=1, description="Minimum required seats")
    site_code: str | None = Field(
        default=None, description="Optional site: GD3, KM or HL"
    )
    room_type: str | None = Field(
        default=None,
        description="Optional type such as MEETING, PROJECT, SEMINAR or LECTURE",
    )
    required_equipment: str | None = Field(
        default=None,
        description="Optional equipment keyword such as projector or video conference",
    )


@tool(args_schema=RoomCatalogSchema)
async def list_meeting_rooms(
    min_capacity: int = 1,
    site_code: str | None = None,
    room_type: str | None = None,
    required_equipment: str | None = None,
) -> str:
    """List UET room codes and operational attributes from the real catalog.

    Returns rooms of every status (ACTIVE, MAINTENANCE, RESTRICTED) so the
    assistant can answer "which rooms are MAINTENANCE/RESTRICTED" from live data.
    Booking selection must still prefer ACTIVE rooms, and the Booking service
    independently refuses a non-ACTIVE room on write.
    """
    result = await list_rooms_db()
    if result.get("status") != "success":
        return json.dumps(result, ensure_ascii=False)

    normalized_site = site_code.strip().upper() if site_code else None
    normalized_type = room_type.strip().upper() if room_type else None
    equipment_keyword = (
        required_equipment.strip().lower() if required_equipment else None
    )
    matching_rooms = []

    for room_code, details in result["rooms"].items():
        if int(details.get("capacity", 0)) < min_capacity:
            continue
        if normalized_site and details.get("site_code") != normalized_site:
            continue
        if normalized_type and details.get("room_type") != normalized_type:
            continue
        equipment = [str(item) for item in details.get("equipment", [])]
        if equipment_keyword and not any(
            equipment_keyword in item.lower() for item in equipment
        ):
            continue
        matching_rooms.append({"room_code": room_code, **details})

    matching_rooms.sort(key=lambda item: (int(item["capacity"]), item["room_code"]))
    return json.dumps(
        {
            "status": "success",
            "source_status": "illustrative",
            "rooms": matching_rooms,
        },
        ensure_ascii=False,
    )


@tool(args_schema=BookingSchema)
async def book_meeting_room(
    room_name: str,
    start_time: str,
    duration_minutes: int,
    purpose: str,
    config: RunnableConfig,
) -> str:
    """
    Đặt phòng họp (book a meeting room). Requires human approval before execution.

    The slot is checked for conflicts BEFORE the approval pause: when it is
    occupied the tool returns status='error', error_code='conflict' right away
    (own_conflict=True plus conflicting_booking_id when the blocking booking
    belongs to the caller) so the assistant can refuse without pausing the
    user. Free slots — including slots that start after an older booking's
    end time — proceed to the normal approval + write flow.
    Returns a JSON result: status='success' with booking_id, or status='error'
    with error_code in {'conflict', 'invalid_time', 'invalid', 'unavailable'}.
    """
    user_id = config["configurable"].get("user_id", "uet-user")

    # Fast-fail BEFORE asking for approval: an occupied slot is refused
    # proactively so the user is never paused for a booking that cannot
    # succeed. A slot that only starts after an older booking's end time is
    # reported available and proceeds to the normal approval flow.
    availability = await check_booking_availability(
        room_name, start_time, duration_minutes, user_id
    )
    if availability.get("status") == "error":
        return json.dumps(availability, ensure_ascii=False)
    if not availability.get("available", False):
        conflict = availability.get("conflict") or {}
        own = bool(availability.get("own_conflict"))
        window = f"{conflict.get('start_at')} -> {conflict.get('end_at')}"
        if own:
            message = (
                f"Khung giờ này đã có lịch của chính bạn: {conflict.get('room')} "
                f"{window} (mã đặt phòng {conflict.get('booking_id')}, mục đích: "
                f"'{conflict.get('purpose')}'). Muốn đặt mới thì phải hủy lịch cũ đó trước."
            )
        else:
            message = (
                f"Phòng {room_name} đã được người khác đặt trong khoảng {window}. "
                f"Không thể hủy lịch của người khác; hãy chọn giờ khác hoặc phòng khác."
            )
        return json.dumps(
            {
                "status": "error",
                "error_code": "conflict",
                "own_conflict": own,
                "conflicting_booking_id": conflict.get("booking_id") if own else None,
                "message": message,
            },
            ensure_ascii=False,
        )

    # Human-in-the-loop: pause BEFORE any write to the database.
    decision = interrupt(
        {
            "action": "book_room",
            "details": {
                "room": room_name,
                "time": start_time,
                "duration_minutes": duration_minutes,
                "purpose": purpose,
                "user_id": user_id,
            },
            "message": f"Xác nhận đặt phòng {room_name} lúc {start_time} ({duration_minutes} phút) cho: {purpose}?",
        }
    )

    if not (isinstance(decision, dict) and decision.get("approved")):
        return json.dumps(
            {
                "status": "rejected",
                "message": "Người dùng đã từ chối đặt phòng. Không có phòng nào được đặt.",
            },
            ensure_ascii=False,
        )

    result = await create_booking_db(
        room_name, start_time, duration_minutes, purpose, user_id
    )
    return json.dumps(result, ensure_ascii=False)


@tool
async def list_my_bookings(config: RunnableConfig) -> str:
    """
    Xem danh sách các phòng tôi đã đặt (list my meeting room bookings).
    Returns a JSON result with the bookings of the current user from the database.
    """
    user_id = config["configurable"].get("user_id", "uet-user")
    result = await list_bookings_db(user_id)
    return json.dumps(result, ensure_ascii=False)


class CancelSchema(BaseModel):
    """Arguments required to cancel a booking."""

    booking_id: str = Field(
        description="ID of the booking to cancel, e.g. 'bk-1a2b3c4d'"
    )


@tool(args_schema=CancelSchema)
async def cancel_booking(booking_id: str, config: RunnableConfig) -> str:
    """
    Hủy một lịch đặt phòng (cancel a meeting room booking). Requires human approval.
    Returns a JSON result: status='success' when cancelled, or status='error'.
    """
    user_id = config["configurable"].get("user_id", "uet-user")

    decision = interrupt(
        {
            "action": "cancel_booking",
            "details": {"booking_id": booking_id, "user_id": user_id},
            "message": f"Xác nhận hủy đặt phòng {booking_id}?",
        }
    )

    if not (isinstance(decision, dict) and decision.get("approved")):
        return json.dumps(
            {
                "status": "rejected",
                "message": "Người dùng đã từ chối hủy. Đặt phòng được giữ nguyên.",
            },
            ensure_ascii=False,
        )

    result = await cancel_booking_db(booking_id, user_id)
    return json.dumps(result, ensure_ascii=False)


class RescheduleSchema(BaseModel):
    """Arguments required to reschedule an existing booking."""

    booking_id: str = Field(
        description="ID of the booking to reschedule, e.g. 'bk-1a2b3c4d'"
    )
    new_start_time: str = Field(
        description="New start time in format 'YYYY-MM-DD HH:MM', e.g. '2026-09-01 15:00'"
    )
    new_duration_minutes: int = Field(
        default=60, description="New meeting duration in minutes, default 60"
    )


@tool(args_schema=RescheduleSchema)
async def reschedule_booking(
    booking_id: str,
    new_start_time: str,
    new_duration_minutes: int,
    config: RunnableConfig,
) -> str:
    """
    Đổi lịch một đặt phòng họp đã có (reschedule a meeting room booking).
    Requires human approval before anything is written.

    The ROOM cannot be changed by this tool — to move to another room the
    assistant must cancel the old booking and create a new one (one approval
    per action). Ownership is enforced here: the booking must appear in the
    caller's own list (PATCH /bookings/{id} does not filter by user itself).
    Returns a JSON result: status='success' with the new time window, or
    status='error' with error_code in {'not_found', 'conflict', 'invalid_time',
    'invalid', 'unavailable'}.
    """
    user_id = config["configurable"].get("user_id", "uet-user")

    # Ownership check: only proceed when the booking belongs to the caller.
    # list_bookings_db already filters by user_id, so "not in my list" means
    # "not yours (or does not exist)" — refuse WITHOUT pausing the user.
    mine = await list_bookings_db(user_id)
    if mine.get("status") == "error":
        return json.dumps(mine, ensure_ascii=False)

    current = None
    for item in mine.get("bookings", []):
        if item["booking_id"] == booking_id.strip():
            current = item
            break

    if current is None:
        return json.dumps(
            {
                "status": "error",
                "error_code": "forbidden",
                "message": (
                    f"Đặt phòng '{booking_id}' không có trong danh sách của bạn "
                    "(không tồn tại hoặc thuộc về người khác) — bạn chỉ có thể "
                    "đổi lịch của chính mình."
                ),
            },
            ensure_ascii=False,
        )
    if current.get("status") == "cancelled":
        return json.dumps(
            {
                "status": "error",
                "error_code": "invalid",
                "message": f"Đặt phòng '{booking_id}' đã bị hủy trước đó nên không thể đổi lịch.",
            },
            ensure_ascii=False,
        )

    room_name = current["room"]

    # Fast-fail BEFORE asking for approval (same policy as book_meeting_room).
    # Overlap with the booking being moved is EXPECTED (the new window may sit
    # on top of the old one) — only a DIFFERENT booking blocks the reschedule.
    availability = await check_booking_availability(
        room_name, new_start_time, new_duration_minutes, user_id
    )
    if availability.get("status") == "error":
        return json.dumps(availability, ensure_ascii=False)
    if not availability.get("available", False):
        conflict = availability.get("conflict") or {}
        if conflict.get("booking_id") != booking_id.strip():
            window = f"{conflict.get('start_at')} -> {conflict.get('end_at')}"
            return json.dumps(
                {
                    "status": "error",
                    "error_code": "conflict",
                    "message": (
                        f"Khung giờ mới của phòng {room_name} ({window}) đã bị chiếm bởi "
                        f"lịch khác (mã {conflict.get('booking_id')}). Hãy chọn giờ khác."
                    ),
                },
                ensure_ascii=False,
            )

    # Human-in-the-loop: pause BEFORE any write to the database.
    decision = interrupt(
        {
            "action": "reschedule_booking",
            "details": {
                "booking_id": booking_id,
                "room": room_name,
                "time": new_start_time,
                "duration_minutes": new_duration_minutes,
                "user_id": user_id,
            },
            "message": (
                f"Xác nhận đổi lịch đặt phòng {room_name} (mã {booking_id}) sang "
                f"{new_start_time} ({new_duration_minutes} phút)?"
            ),
        }
    )

    if not (isinstance(decision, dict) and decision.get("approved")):
        return json.dumps(
            {
                "status": "rejected",
                "message": "Người dùng đã từ chối đổi lịch. Lịch cũ được giữ nguyên.",
            },
            ensure_ascii=False,
        )

    result = await update_booking_db(
        booking_id, new_start_time, new_duration_minutes, user_id
    )
    return json.dumps(result, ensure_ascii=False)


def get_booking_tools():
    """Return the exact tools of the booking agent."""
    return [
        list_meeting_rooms,
        book_meeting_room,
        list_my_bookings,
        cancel_booking,
        reschedule_booking,
    ]


# Tên ngày tiếng Việt — strftime('%A') trả tiếng Anh trong khi product language
# là tiếng Việt (prompt booking.md quy đổi "thứ Sáu"/"ngày mai" theo ngày này).
_WEEKDAY_VI = [
    "thứ Hai",
    "thứ Ba",
    "thứ Tư",
    "thứ Năm",
    "thứ Sáu",
    "thứ Bảy",
    "Chủ Nhật",
]


def _today_vietnamese() -> str:
    """Ngày hiện tại dạng 'YYYY-MM-DD (thứ ...)' cho prompt booking."""
    now = datetime.now()
    return f"{now.strftime('%Y-%m-%d')} ({_WEEKDAY_VI[now.weekday()]})"


def build_booking_graph(llm: BaseChatModel):
    """Build the booking ReAct subgraph with the booking prompt."""
    return create_react_subgraph(
        llm, get_booking_tools(), "booking", prompt_vars={"today": _today_vietnamese()}
    )
