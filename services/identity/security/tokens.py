# ============================================
# services/identity/security/tokens.py
# ============================================
"""
JWT issuing and verification (HS256).

Token claims: iss, sub (user_id), email, name, iat, exp — per hint.md.
"""

import logging
from datetime import UTC, datetime, timedelta

import jwt

from ..settings import settings

logger = logging.getLogger(__name__)


def create_access_token(user_id: str, email: str, name: str) -> str:
    """
    Issue a signed JWT for one authenticated user.

    Args:
        user_id: Unique user identifier (goes into the 'sub' claim).
        email: User email (goes into the 'email' claim).
        name: Display name (goes into the 'name' claim).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(UTC)
    payload = {
        "iss": settings.JWT_ISSUER,
        "sub": user_id,
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict | None:
    """
    Verify and decode a JWT.

    Args:
        token: Encoded JWT string.

    Returns:
        The claims dict when the token is valid, otherwise None.
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
        )
    except jwt.PyJWTError as error:
        logger.warning("JWT decode failed: %s", error)
        return None
