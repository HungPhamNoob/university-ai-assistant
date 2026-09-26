# ============================================
# services/booking/auth.py
# ============================================
"""
Authentication dependency of the Booking service.

Two accepted callers:
1. Production traffic through the API Gateway: Kong proves itself with the
   X-Gateway-Token header and injects the authenticated X-User-Id.
2. Direct service-to-service calls (agent -> booking) carrying the shared
   X-Internal-Token header (local development and internal flows).
"""

from fastapi import Header, HTTPException

from .settings import settings


def verify_booking_access(
    x_gateway_token: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str | None:
    """
    Verify that the request comes from the gateway or an internal service.

    Args:
        x_gateway_token: Value of the X-Gateway-Token header (Kong).
        x_internal_token: Value of the X-Internal-Token header (agent service).
        x_user_id: User id injected by the gateway.

    Returns:
        The gateway-injected user id when present, otherwise None
        (internal service calls pass the owner inside the payload).

    Raises:
        HTTPException: 401 when neither credential is valid.
    """
    if x_internal_token == settings.INTERNAL_API_TOKEN:
        return x_user_id
    if x_gateway_token == settings.GATEWAY_SHARED_SECRET:
        return x_user_id
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing X-Internal-Token / X-Gateway-Token",
    )
