# ============================================
# services/conversation/auth.py
# ============================================
"""
Authentication helpers for the Conversation service.

- read_gateway_user: for user-facing endpoints behind the API Gateway.
  Soft check for local development: when the gateway headers are missing the
  caller is treated as unauthenticated (None) instead of being rejected.
- verify_internal_token: for service-to-service calls (agent -> conversation)
  using the shared X-Internal-Api-Token header.
"""

from fastapi import Header, HTTPException

from .settings import settings


def verify_internal_token(x_internal_api_token: str = Header(default="")) -> None:
    """
    Verify the shared internal token on internal endpoints.

    Args:
        x_internal_api_token: Value of the X-Internal-Api-Token request header.

    Raises:
        HTTPException: 401 when the token is missing or invalid.
    """
    if x_internal_api_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(
            status_code=401, detail="Invalid or missing X-Internal-Api-Token"
        )


def read_gateway_user(
    x_gateway_token: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str | None:
    """
    Extract the user id injected by the API Gateway, when present.

    Args:
        x_gateway_token: Value of the X-Gateway-Token header.
        x_user_id: User id injected by the gateway.

    Returns:
        The user id when a valid gateway context is present, otherwise None.
    """
    if x_gateway_token and x_gateway_token == settings.GATEWAY_SHARED_SECRET:
        return x_user_id
    return None
