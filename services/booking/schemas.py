# ============================================
# services/booking/schemas.py
# ============================================
"""
Pydantic request/response schemas and domain enums of the Booking service API.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BookingStatus(str, Enum):
    """Lifecycle states of a booking."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingCreate(BaseModel):
    """Request body for creating a booking."""

    # Optional: the trusted X-User-Id header (gateway/internal) overrides this
    # field, so callers authenticating through the gateway may omit it.
    user_id: str | None = Field(
        default=None, min_length=1, description="Owner of the booking"
    )
    room: str = Field(..., min_length=1, description="UET room code, e.g. GD3-402")
    purpose: str = Field(..., min_length=3, description="Purpose of the meeting")
    start_at: datetime = Field(..., description="Start time (ISO 8601)")
    end_at: datetime = Field(..., description="End time (ISO 8601)")


class BookingUpdate(BaseModel):
    """Request body for partially updating a booking."""

    purpose: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: str | None = None


class BookingResponse(BaseModel):
    """Booking representation returned to callers."""

    booking_id: str
    user_id: str
    room: str
    purpose: str
    start_at: datetime
    end_at: datetime
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Simple message payload used for delete/cancel results."""

    message: str
    booking_id: str | None = None
