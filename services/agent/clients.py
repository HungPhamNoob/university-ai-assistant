# ============================================
# services/agent/clients.py
# ============================================
"""
Internal HTTP clients for real service-to-service communication.

No mock data: every call goes to the actual RAG or Booking microservice.
When a service is unreachable the functions return structured error payloads
so the LLM can honestly tell the user instead of pretending success.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

BOOKING_BASE_URL = f"{settings.BOOKING_SERVICE_URL}/api/business/bookings"
CONVERSATION_BASE_URL = f"{settings.CONVERSATION_SERVICE_URL}/internal/conversations"
INTERNAL_HEADERS = {"X-Internal-Token": settings.INTERNAL_API_TOKEN}
# The conversation service verifies the X-Internal-Api-Token header.
CONVERSATION_HEADERS = {"X-Internal-Api-Token": settings.INTERNAL_API_TOKEN}


def booking_headers(user_id: str) -> dict[str, str]:
    """
    Headers for Booking service calls: internal token PLUS the end-user
    identity, so the Booking service can enforce ownership (X-User-Id always
    wins over any query parameter on its routers).
    """
    return {**INTERNAL_HEADERS, "X-User-Id": user_id}


async def search_kb(query: str, top_k: int = 5) -> str:
    """
    Call the RAG service to retrieve internal context for a query.

    Args:
        query: Search query from the FAQ agent.
        top_k: Number of chunks to retrieve.

    Returns:
        Concatenated chunk texts, or a short Vietnamese notice when nothing
        relevant was found or the RAG service is unavailable.
    """
    url = f"{settings.RAG_SERVICE_URL}/api/kb/search"
    payload = {"query": query, "top_k": top_k}

    async with httpx.AsyncClient(timeout=settings.RAG_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(url, json=payload, headers=INTERNAL_HEADERS)
            response.raise_for_status()
            data = response.json()
            contexts = [
                result["text"]
                for result in data.get("results", [])
                if result.get("text")
            ]
            if contexts:
                return "\n\n---\n\n".join(contexts)
            return "Không tìm thấy thông tin liên quan trong tài liệu nội bộ."
        except Exception as error:  # noqa: BLE001 - tool must degrade gracefully
            logger.error("RAG service call failed: %s", error)
            return (
                "Lỗi kết nối đến hệ thống tài liệu nội bộ (RAG). Vui lòng thử lại sau."
            )


async def list_rooms_db() -> dict[str, Any]:
    """Fetch the illustrative UET room registry from the Booking service."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                f"{BOOKING_BASE_URL}/rooms",
                headers=INTERNAL_HEADERS,
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as error:
            logger.error("Room catalog call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Không thể lấy danh mục phòng UET lúc này.",
            }

    return {
        "status": "success",
        "source_status": "illustrative",
        "rooms": response.json(),
    }


async def create_booking_db(
    room_name: str, start_time: str, duration_minutes: int, purpose: str, user_id: str
) -> dict[str, Any]:
    """
    Persist a new booking through the Booking domain service.

    Args:
        room_name: Room to book.
        start_time: Start time in 'YYYY-MM-DD HH:MM' format.
        duration_minutes: Meeting duration in minutes.
        purpose: Meeting purpose.
        user_id: Owner of the booking.

    Returns:
        Dict with status='success' and the booking on 201, otherwise
        status='error' with an error_code in
        {'invalid_time', 'conflict', 'invalid', 'unavailable'}.
    """
    try:
        start_at = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return {
            "status": "error",
            "error_code": "invalid_time",
            "message": f"Thời gian '{start_time}' không hợp lệ, cần đúng định dạng 'YYYY-MM-DD HH:MM'.",
        }

    payload = {
        "user_id": user_id,
        "room": room_name.strip(),
        "purpose": purpose.strip(),
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(minutes=duration_minutes)).isoformat(),
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                BOOKING_BASE_URL, json=payload, headers=booking_headers(user_id)
            )
        except httpx.HTTPError as error:
            logger.error("Booking service call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Dịch vụ đặt phòng đang tạm thời không khả dụng, vui lòng thử lại sau.",
            }

    if response.status_code == 201:
        booking = response.json()
        return {
            "status": "success",
            "message": "Đã đặt phòng thành công.",
            "booking_id": booking["booking_id"],
            "room": booking["room"],
            "start_at": booking["start_at"],
            "end_at": booking["end_at"],
            "purpose": booking["purpose"],
        }
    if response.status_code == 409:
        return {
            "status": "error",
            "error_code": "conflict",
            "message": response.json().get(
                "detail", "Phòng đã được đặt trong khung giờ này."
            ),
        }
    detail = response.json().get("detail", "Yêu cầu đặt phòng không hợp lệ.")
    code = "invalid_time" if "past" in str(detail).lower() else "invalid"
    return {
        "status": "error",
        "error_code": code,
        "message": detail,
    }


async def check_booking_availability(
    room_name: str, start_time: str, duration_minutes: int, user_id: str
) -> dict[str, Any]:
    """
    Read-only availability probe called BEFORE the human-approval interrupt.

    This lets the assistant refuse an occupied slot proactively instead of
    pausing the user for an approval that cannot succeed.

    Args:
        room_name: Room to book.
        start_time: Start time in 'YYYY-MM-DD HH:MM' format.
        duration_minutes: Meeting duration in minutes.
        user_id: Requesting user, used to detect own-vs-foreign conflicts.

    Returns:
        Dict with available=True when the slot is free; available=False with
        own_conflict and the blocking booking under 'conflict' when occupied;
        or status='error' with error_code in
        {'invalid_time', 'invalid', 'unavailable'}.
    """
    try:
        start_at = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return {
            "status": "error",
            "error_code": "invalid_time",
            "message": f"Thời gian '{start_time}' không hợp lệ, cần đúng định dạng 'YYYY-MM-DD HH:MM'.",
        }

    params = {
        "room": room_name.strip(),
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(minutes=duration_minutes)).isoformat(),
        "user_id": user_id,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                f"{BOOKING_BASE_URL}/check",
                params=params,
                headers=booking_headers(user_id),
            )
        except httpx.HTTPError as error:
            logger.error("Booking service call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Dịch vụ đặt phòng đang tạm thời không khả dụng, vui lòng thử lại sau.",
            }

    if response.status_code == 200:
        return response.json()

    detail = response.json().get("detail", "Yêu cầu đặt phòng không hợp lệ.")
    code = "invalid_time" if "past" in str(detail).lower() else "invalid"
    return {"status": "error", "error_code": code, "message": detail}


async def list_bookings_db(user_id: str) -> dict[str, Any]:
    """
    Fetch the bookings of one user from the Booking domain service.

    Args:
        user_id: Owner of the bookings.

    Returns:
        Dict with status='success' and a bookings list, status='empty' when
        the user has no bookings, or status='error' on failures.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                BOOKING_BASE_URL,
                params={"user_id": user_id},
                headers=booking_headers(user_id),
            )
        except httpx.HTTPError as error:
            logger.error("Booking service call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Không thể kết nối dịch vụ đặt phòng.",
            }

    if response.status_code != 200:
        return {
            "status": "error",
            "error_code": "unavailable",
            "message": "Không thể lấy danh sách đặt phòng.",
        }

    bookings = response.json()
    if not bookings:
        return {"status": "empty", "message": "Bạn chưa đặt phòng nào."}
    return {
        "status": "success",
        "bookings": [
            {
                "booking_id": item["booking_id"],
                "room": item["room"],
                "start_at": item["start_at"],
                "end_at": item["end_at"],
                "purpose": item["purpose"],
                "status": item["status"],
            }
            for item in bookings
        ],
    }


async def cancel_booking_db(booking_id: str, user_id: str) -> dict[str, Any]:
    """
    Cancel one booking through the Booking domain service.

    Args:
        booking_id: Booking identifier to cancel.
        user_id: Owner check; foreign bookings are rejected by the service.

    Returns:
        Dict with status='success' when cancelled, otherwise status='error'
        with error_code in {'not_found', 'invalid', 'unavailable'}.
    """
    url = f"{BOOKING_BASE_URL}/{booking_id.strip()}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.delete(
                url, params={"user_id": user_id}, headers=booking_headers(user_id)
            )
        except httpx.HTTPError as error:
            logger.error("Booking service call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Không thể kết nối dịch vụ đặt phòng.",
            }

    if response.status_code == 200:
        return {
            "status": "success",
            "message": "Đã hủy đặt phòng thành công.",
            "booking_id": booking_id,
        }

    if response.status_code == 403:
        return {
            "status": "error",
            "error_code": "forbidden",
            "message": (
                "Đặt phòng này thuộc về người khác — bạn chỉ có thể hủy lịch "
                "của chính mình."
            ),
        }

    detail = response.json().get("detail", "Không thể hủy đặt phòng.")
    code = "not_found" if response.status_code == 404 else "invalid"
    return {"status": "error", "error_code": code, "message": detail}


async def update_booking_db(
    booking_id: str, start_time: str, duration_minutes: int, user_id: str
) -> dict[str, Any]:
    """
    Reschedule one booking through the Booking domain service (PATCH).

    The caller (reschedule tool) already verified the booking belongs to the
    user via list_bookings_db; the X-User-Id header makes the Booking service
    enforce the same ownership rule server-side (403 on foreign bookings).

    Args:
        booking_id: Booking to reschedule.
        start_time: New start time in 'YYYY-MM-DD HH:MM' format.
        duration_minutes: New meeting duration in minutes.
        user_id: Requesting user — sent as X-User-Id so the Booking service
            enforces ownership (foreign bookings are refused with 403).

    Returns:
        Dict with status='success' and the new time window, or status='error'
        with error_code in {'invalid_time', 'not_found', 'conflict', 'invalid',
        'unavailable'}.
    """
    try:
        start_at = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return {
            "status": "error",
            "error_code": "invalid_time",
            "message": f"Thời gian '{start_time}' không hợp lệ, cần đúng định dạng 'YYYY-MM-DD HH:MM'.",
        }

    url = f"{BOOKING_BASE_URL}/{booking_id.strip()}"
    payload = {
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(minutes=duration_minutes)).isoformat(),
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.patch(
                url, json=payload, headers=booking_headers(user_id)
            )
        except httpx.HTTPError as error:
            logger.error("Booking service call failed: %s", error)
            return {
                "status": "error",
                "error_code": "unavailable",
                "message": "Không thể kết nối dịch vụ đặt phòng.",
            }

    if response.status_code == 200:
        booking = response.json()
        return {
            "status": "success",
            "message": "Đã đổi lịch đặt phòng thành công.",
            "booking_id": booking["booking_id"],
            "room": booking["room"],
            "start_at": booking["start_at"],
            "end_at": booking["end_at"],
            "purpose": booking["purpose"],
        }
    if response.status_code == 404:
        return {
            "status": "error",
            "error_code": "not_found",
            "message": f"Không tìm thấy đặt phòng '{booking_id}'.",
        }
    if response.status_code == 403:
        return {
            "status": "error",
            "error_code": "forbidden",
            "message": (
                "Đặt phòng này thuộc về người khác — bạn chỉ có thể đổi lịch "
                "của chính mình."
            ),
        }
    if response.status_code == 409:
        return {
            "status": "error",
            "error_code": "conflict",
            "message": response.json().get(
                "detail", "Khung giờ mới trùng với một lịch đặt khác."
            ),
        }

    detail = response.json().get("detail", "Yêu cầu đổi lịch không hợp lệ.")
    code = "invalid_time" if "past" in str(detail).lower() else "invalid"
    return {"status": "error", "error_code": code, "message": detail}


async def sync_conversation_thread(
    thread_id: str, user_id: str, messages: list[dict[str, str]]
) -> dict[str, Any]:
    """
    Persist a finished chat turn into the Conversation service.

    The conversation row is auto-created by the service when it does not
    exist yet, so this call is safe on the very first message of a thread.
    Summarization of the thread's old messages is decided server-side by the
    episodic service (threshold-based) — there is no summarize flag anymore.
    This is a best-effort operation: failures only log and never break chat.

    Args:
        thread_id: LangGraph thread id, reused as the conversation id.
        user_id: Owner of the conversation.
        messages: List of {"role": "user"|"assistant", "content": str}.

    Returns:
        Dict with status='success' and the sync action, or status='error'.
    """
    url = f"{CONVERSATION_BASE_URL}/{thread_id}/messages"
    payload = {
        "messages": messages,
        "user_id": user_id,
        "title": "UET assistant conversation",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.put(url, json=payload, headers=CONVERSATION_HEADERS)
            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Conversation synced thread=%s action=%s",
                    thread_id,
                    data.get("action"),
                )
                return {"status": "success", "action": data.get("action", "unknown")}
            logger.warning(
                "Conversation sync rejected thread=%s code=%s",
                thread_id,
                response.status_code,
            )
            return {"status": "error", "code": response.status_code}
        except httpx.HTTPError as error:
            logger.warning("Conversation service unreachable: %s", error)
            return {"status": "error", "code": "unavailable"}


async def fetch_memory_context(
    conversation_id: str, user_id: str, query: str
) -> dict[str, Any] | None:
    """
    Fetch episodic memory context for one turn from the Conversation service.

    Independent-thread policy (reference C/D): the conversation service
    returns ONLY the current thread's own rolling episode — memory of other
    conversations is never injected. This is strictly best-effort: when the
    service is unreachable, returns a non-200, or the memory has not been
    built yet, this returns None so the turn proceeds without memory and
    never crashes.

    Args:
        conversation_id: LangGraph thread id, reused as the conversation id.
        user_id: Owner of the conversation (scopes retrieval).
        query: Latest user message (accepted for API stability; unused since
            cross-thread similarity search was removed).

    Returns:
        The response JSON dict, or None when memory is unavailable.
    """
    url = f"{CONVERSATION_BASE_URL}/{conversation_id}/memory"
    params = {"user_id": user_id, "query": query}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                url, params=params, headers=CONVERSATION_HEADERS
            )
    except httpx.HTTPError as error:
        logger.warning(
            "Memory fetch unavailable (thread=%s): %s", conversation_id, error
        )
        return None

    if response.status_code != 200:
        logger.debug(
            "Memory fetch returned status=%s thread=%s",
            response.status_code,
            conversation_id,
        )
        return None

    try:
        return response.json()
    except ValueError as error:
        logger.warning(
            "Memory fetch returned invalid JSON (thread=%s): %s", conversation_id, error
        )
        return None
