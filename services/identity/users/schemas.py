# ============================================
# services/identity/users/schemas.py
# ============================================
"""
Pydantic request/response schemas of the users feature.
"""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Lightweight RFC-5322-style email pattern (avoids the email-validator dependency).
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate_email(value: str) -> str:
    """
    Validate and normalize an email address.

    Args:
        value: Raw email string from the request.

    Returns:
        The lowercased email.

    Raises:
        ValueError: When the format is invalid.
    """
    email = value.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Invalid email format")
    return email


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: str = Field(
        ..., min_length=5, max_length=255, description="Unique login email"
    )
    password: str = Field(
        ..., min_length=6, max_length=128, description="Plain password"
    )
    name: str = Field(..., min_length=1, max_length=128, description="Display name")

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        """Pydantic hook that validates the email field."""
        return _validate_email(value)


class LoginRequest(BaseModel):
    """Request body for user login."""

    email: str = Field(..., min_length=5, description="Login email")
    password: str = Field(..., min_length=1, description="Plain password")

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        """Pydantic hook that validates the email field."""
        return _validate_email(value)


class UserProfile(BaseModel):
    """Public representation of a user."""

    user_id: str
    email: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Payload returned after register/login: JWT plus profile."""

    token: str
    token_type: str = "bearer"
    user: UserProfile
