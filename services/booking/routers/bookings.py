# ============================================
# services/booking/routers/bookings.py
# ============================================
"""
HTTP endpoints of the Booking domain service:
POST /bookings · GET /bookings · GET /check · GET /{id} · PATCH /{id} · DELETE /{id}

All endpoints require the shared X-Internal-Token header.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import verify_booking_access
from ..rules import BookingConflictError, BookingNotFoundError
from ..schemas import BookingCreate, BookingResponse, BookingUpdate, MessageResponse
from ..service import BookingService

# verify_booking_access trả về X-User-Id tin cậy (Kong inject từ JWT, hoặc
# internal service set cho end-user) — mỗi handler khai báo nó như một
# parameter thay vì router-level Depends để LẤY ĐƯỢC giá trị đó.
router = APIRouter()


def get_service(request: Request) -> BookingService:
    """
    Resolve the BookingService instance created at application startup.

    Args:
        request: Incoming HTTP request carrying the application state.

    Returns:
        The shared BookingService.
    """
    return request.app.state.booking_service


def resolve_user_id(caller_user_id: str | None, query_user_id: str | None) -> str:
    """
    Resolve the owner identity of a booking operation.

    The X-User-Id header ALWAYS wins: through the gateway it is overwritten
    by Kong from the verified JWT, and internal services set it to the
    end-user they act for. The query param stays only as a fallback for
    legacy internal callers; an external client cannot use it to impersonate
    anyone because the header replaces it on the gateway path.

    Args:
        caller_user_id: Value returned by verify_booking_access (header).
        query_user_id: Legacy ?user_id= query parameter.

    Returns:
        The effective user id.

    Raises:
        HTTPException: 400 when neither source carries an identity.
    """
    user_id = caller_user_id or query_user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user identity (X-User-Id)")
    return user_id


@router.get("/rooms", response_model=dict[str, dict[str, object]])
async def list_rooms(
    service: BookingService = Depends(get_service),
    _auth: str | None = Depends(verify_booking_access),
) -> dict[str, dict[str, object]]:
    """
    List the meeting room catalog with capacities.

    Returns:
        Mapping of room name to seat count.
    """
    return service.list_rooms()


@router.post("", response_model=BookingResponse, status_code=201)
async def create_booking(
    payload: BookingCreate,
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
) -> BookingResponse:
    """
    Create a new booking after conflict validation.

    Args:
        payload: Booking creation data.
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header;
            when present it overrides payload.user_id so a caller can never
            create a booking owned by someone else.

    Returns:
        The created booking.
    """
    data = payload
    owner = caller_user_id or payload.user_id
    if not owner:
        raise HTTPException(status_code=400, detail="Missing user identity (X-User-Id)")
    if owner != payload.user_id:
        data = payload.model_copy(update={"user_id": owner})
    try:
        return await service.create_booking(data)
    except BookingConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("", response_model=list[BookingResponse])
async def list_bookings(
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
    user_id: str | None = Query(default=None),
) -> list[BookingResponse]:
    """
    List all bookings of one user (never of another user).

    Args:
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header.
        user_id: Legacy query parameter fallback.

    Returns:
        List of bookings of the resolved user, newest first.
    """
    return await service.list_bookings(resolve_user_id(caller_user_id, user_id))


@router.get("/check")
async def check_availability(
    room: str,
    start_at: datetime,
    end_at: datetime,
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
    user_id: str | None = Query(default=None),
) -> dict[str, object]:
    """
    Read-only availability probe used by the agent BEFORE the HITL approval.

    Declared before /{booking_id} so 'check' is never parsed as an id.

    Args:
        room: Room name to check.
        start_at: Requested start time (ISO 8601).
        end_at: Requested end time (ISO 8601).
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header.
        user_id: Legacy query parameter fallback (own-vs-foreign conflicts).

    Returns:
        {'available': bool, 'own_conflict': bool, 'conflict': {...} | None}.
    """
    owner = resolve_user_id(caller_user_id, user_id)
    try:
        return await service.check_availability(room, start_at, end_at, owner)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: str,
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
    user_id: str | None = Query(default=None),
) -> BookingResponse:
    """
    Fetch one booking by id — only its owner may read it.

    Args:
        booking_id: Unique booking identifier.
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header.
        user_id: Legacy query parameter fallback.

    Returns:
        The booking.
    """
    owner = resolve_user_id(caller_user_id, user_id)
    try:
        return await service.get_booking(booking_id, owner)
    except BookingNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.patch("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: str,
    payload: BookingUpdate,
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
    user_id: str | None = Query(default=None),
) -> BookingResponse:
    """
    Partially update one booking — only its owner may reschedule it.

    Args:
        booking_id: Unique booking identifier.
        payload: Fields to update.
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header.
        user_id: Legacy query parameter fallback.

    Returns:
        The updated booking.
    """
    owner = resolve_user_id(caller_user_id, user_id)
    try:
        return await service.update_booking(booking_id, payload, owner)
    except BookingNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except BookingConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/{booking_id}", response_model=MessageResponse)
async def delete_booking(
    booking_id: str,
    service: BookingService = Depends(get_service),
    caller_user_id: str | None = Depends(verify_booking_access),
    user_id: str | None = Query(default=None),
) -> MessageResponse:
    """
    Cancel one booking by setting its status to cancelled — owner only.

    Args:
        booking_id: Unique booking identifier.
        service: Booking use-case service.
        caller_user_id: Trusted identity from the gateway/internal header.
        user_id: Legacy query parameter fallback.

    Returns:
        Confirmation message with the booking id.
    """
    owner = resolve_user_id(caller_user_id, user_id)
    try:
        await service.cancel_booking(booking_id, user_id=owner)
    except BookingNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return MessageResponse(message="Booking cancelled", booking_id=booking_id)
