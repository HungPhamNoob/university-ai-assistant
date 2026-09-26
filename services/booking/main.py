# ============================================
# services/booking/main.py
# ============================================
"""
Entrypoint of the Booking domain service.

Run with:
    uvicorn services.booking.main:app --reload --port 8003
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE building settings so Postgres credentials are picked up.
load_dotenv()

import uvicorn
from fastapi import FastAPI

from .database import build_engine, build_session_factory
from .repository import BookingRepository
from .routers.bookings import router as booking_router
from .service import BookingService
from .settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: build the database engine and wire the
    repository + service into app.state.

    Schema do Alembic quản lý (services/booking/migrations/) — container
    start chạy `alembic upgrade head` trước khi serve, KHÔNG create_all ở đây.
    """
    engine = build_engine()
    session_factory = build_session_factory(engine)
    repository = BookingRepository(session_factory)
    app.state.booking_service = BookingService(repository)
    logger.info("Booking service ready (db=%s)", settings.POSTGRES_DB)
    yield
    await engine.dispose()


app = FastAPI(
    title="Booking Domain Service",
    version="1.0.0",
    description="Internal service that persists meeting room bookings.",
    lifespan=lifespan,
)

app.include_router(booking_router, prefix="/api/business/bookings", tags=["booking"])


@app.get("/health")
async def health() -> dict:
    """
    Liveness probe for infrastructure checks.

    Returns:
        Simple status payload.
    """
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("services.booking.main:app", host="0.0.0.0", port=8003, reload=True)
