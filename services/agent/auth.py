# ============================================
# services/agent/auth.py
# ============================================
"""
Gateway authentication for the Agent service.

In production every request must pass through the API Gateway (Kong), which
proves itself with the shared X-Gateway-Token header and injects the
authenticated user as X-User-Id / X-User-Email headers.

For local development (CLI, eval scripts) this enforcement is optional and is
controlled by the AGENT_REQUIRE_GATEWAY setting (default: disabled).
"""

import logging

from fastapi import Header, HTTPException

from .config import settings

logger = logging.getLogger(__name__)


def verify_gateway_request(
    x_gateway_token: str = Header(default=""),
    x_user_id: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
) -> dict:
    """
    Verify that the request really comes from the API Gateway.

    Args:
        x_gateway_token: Value of the X-Gateway-Token request header.
        x_user_id: Authenticated user id injected by the gateway.
        x_user_email: Authenticated user email injected by the gateway.

    Returns:
        Dict with the resolved user context: {"user_id": str|None, "email": str|None}.
        When gateway enforcement is disabled (local dev), returns an empty context.

    Raises:
        HTTPException: 401 when enforcement is enabled and the token is missing
            or invalid; 400 when the token is valid but no X-User-Id was injected.
    """
    if not settings.AGENT_REQUIRE_GATEWAY:
        # Local development mode: direct CLI / eval access is allowed.
        return {"user_id": None, "email": None}

    if x_gateway_token != settings.GATEWAY_SHARED_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Requests must go through the API Gateway (invalid X-Gateway-Token)",
        )
    if not x_user_id:
        raise HTTPException(
            status_code=400,
            detail="Gateway did not inject the X-User-Id header",
        )
    return {"user_id": x_user_id, "email": x_user_email}
