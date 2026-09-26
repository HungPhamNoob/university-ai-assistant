#!/usr/bin/env python3
# ============================================
# eval/service_smoke_test.py
# ============================================
"""
End-to-end smoke test of every service in the UET AI stack.

What it does
============
Runs real HTTP requests (no mocks, no fixtures) against the running services and
asserts both the API contract and the business rules:

* **Identity**    register (token + profile), email normalization, duplicate 409,
                  validation 422s, login, wrong password 401, unknown email 401,
                  /me with Bearer, /me without auth 401, /me with bad JWT 401,
                  /me through the gateway X-User-Id header (200 and 404).
* **Booking**     room catalog, create, overlap conflict (own + other user),
                  unknown room, capacity limit, past time, end <= start,
                  list, get by id, 404, cancel, rebook after cancel, adjacent
                  slot allowed. Every mutation is re-read through the API.
* **Conversation**create / list / messages / sync skip-append-replace /
                  summarize / episodic memory context / 404 / internal-token 401
                  / delete.
* **RAG**         health, hybrid+HyDE+rerank+MMR search returns grounded chunks,
                  top_k validation, semantic cache stats.
* **Agent**       /health, request validation (422), SSE /api/chat/stream events
                  (agent label + tool start/end + token deltas + done), general
                  chat, FAQ sub-agent calling search_uet_knowledge, Web Search
                  sub-agent calling search_web (Tavily), booking sub-agent asking
                  for a missing field instead of calling a tool, HITL interrupt
                  then /api/chat/resume approve (booking really persisted under
                  the caller's user_id) and reject (nothing persisted, slot free).
                  Called DIRECTLY with simulated gateway headers, so it works
                  with AGENT_REQUIRE_GATEWAY on or off (see Environment below).
* **Frontend**    health, index.html and api.js are served.

Usage
=====
    python eval/service_smoke_test.py            # full run (LLM calls, ~5 min)
    python eval/service_smoke_test.py --fast     # skip the LLM/agent section

Environment
-----------
Service base URLs are read from the same variables as ``cli.py``
(``IDENTITY_SERVICE_URL``, ``BOOKING_SERVICE_URL``, ``CONVERSATION_SERVICE_URL``,
``RAG_SERVICE_URL``, ``FRONTEND_SERVICE_URL``, ``INTERNAL_API_TOKEN``).

The agent is the exception: this script ALWAYS talks to the agent service
directly (``SMOKE_AGENT_URL``, default ``http://localhost:$AGENT_PORT``) and
simulates the gateway itself by sending ``X-Gateway-Token`` +
``X-User-Id`` headers (secret from ``GATEWAY_SHARED_SECRET``). That works with
``AGENT_REQUIRE_GATEWAY`` on or off — unlike ``AGENT_SERVICE_URL``, which may
point at Kong (no /health route there, and Kong demands a JWT).

Exit code is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

IDENTITY_URL = os.getenv("IDENTITY_SERVICE_URL", "http://localhost:8001")
BOOKING_URL = os.getenv("BOOKING_SERVICE_URL", "http://localhost:8003")
CONVERSATION_URL = os.getenv("CONVERSATION_SERVICE_URL", "http://localhost:8004")
RAG_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8002")
# Direct agent URL (see Environment in the docstring) — intentionally NOT
# AGENT_SERVICE_URL, which cli.py may point at the Kong gateway.
AGENT_URL = os.getenv(
    "SMOKE_AGENT_URL", f"http://localhost:{os.getenv('AGENT_PORT', '8000')}"
)
FRONTEND_URL = os.getenv("FRONTEND_SERVICE_URL", "http://localhost:3000")
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "changeme")
GATEWAY_SECRET = os.getenv(
    "GATEWAY_SHARED_SECRET", "gateway-shared-secret-change-in-prod"
)

TIMEOUT = int(os.getenv("SMOKE_TIMEOUT", "180"))
STATE: dict[str, Any] = {}

# A run-unique user so repeated runs never collide on the unique email index.
RUN_ID = uuid.uuid4().hex[:8]
EMAIL = f"smoke_{RUN_ID}@example.com"
PASSWORD = "Smoke!Pass123"

# Deterministic future slots (the booking service rejects past times).
# They are defaults only: resolve_free_slots() moves them to the first window
# that /check reports as free, so rows left over from an earlier run (or from
# the CLI smoke tests) can never make this run fail with a false 409.
TOMORROW = (datetime.now() + timedelta(days=1)).replace(
    hour=14, minute=0, second=0, microsecond=0
)
SLOT_END = TOMORROW + timedelta(minutes=60)
ADJACENT_START = SLOT_END
ADJACENT_END = ADJACENT_START + timedelta(minutes=60)
SMOKE_ROOM = "GD3-402"
BOOKING_USER = f"smoke-book-{RUN_ID}"  # owner for the booking section

# ---------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------
PASSED: list[str] = []
FAILED: list[str] = []


def record(name: str, ok: bool, detail_text: str = "") -> None:
    """Print and store one check result."""
    if ok:
        PASSED.append(name)
        print(f"  \u2705 {name}")
    else:
        FAILED.append(f"{name}: {detail_text}")
        print(f"  \u274c {name} \u2014 {detail_text}")


def run_check(name: str, fn: Callable[[], None]) -> None:
    """Execute one check function, turning exceptions into a FAIL record."""
    try:
        fn()
    except AssertionError as error:
        record(name, False, str(error))
    except requests.RequestException as error:
        record(name, False, f"network error: {error}")
    except Exception as error:  # noqa: BLE001 - report, never crash the suite
        record(name, False, f"{type(error).__name__}: {error}")
    else:
        record(name, True)


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n=== {title} ===")


def expect(condition: Any, message: str) -> None:
    """Assert with a readable message."""
    if not condition:
        raise AssertionError(message)


def detail(response: requests.Response) -> str:
    """Render 'status body' for assertion messages (body truncated)."""
    return f"status={response.status_code} body={response.text[:200]}"


def internal_headers() -> dict[str, str]:
    """Headers accepted by the Booking service internal routes."""
    return {"X-Internal-Token": INTERNAL_TOKEN}


def booking_headers(user_id: str) -> dict[str, str]:
    """Internal token + the user identity Kong would inject (X-User-Id).

    Booking by-id/PATCH routes resolve the owner from X-User-Id (header wins
    over the legacy ?user_id query param); the internal token alone passes the
    auth gate but NOT the identity check.
    """
    return {**internal_headers(), "X-User-Id": user_id}


def conversation_headers() -> dict[str, str]:
    """Headers accepted by the Conversation service internal routes."""
    return {"X-Internal-Api-Token": INTERNAL_TOKEN}


def conv_user_headers(user_id: str) -> dict[str, str]:
    """Identity header for the PUBLIC conversation routes (no token needed).

    Public conversation routes resolve the caller from X-User-Id (header) or
    ?user_id (query); the header mirrors what Kong injects in production.
    """
    return {"X-User-Id": user_id}


# ---------------------------------------------------------------
# 1. Identity service (/auth/register, /auth/login, /auth/me)
# ---------------------------------------------------------------
def check_identity_health() -> None:
    response = requests.get(f"{IDENTITY_URL}/health", timeout=15)
    expect(response.status_code == 200, detail(response))
    expect(
        response.json().get("status") == "ok", f"unexpected payload: {response.json()}"
    )


def check_identity_register() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "name": "Smoke Tester"},
        timeout=30,
    )
    expect(response.status_code == 201, detail(response))
    body = response.json()
    expect(body.get("token"), f"missing token: {body}")
    expect(body.get("token_type") == "bearer", f"unexpected token_type: {body}")
    user = body.get("user") or {}
    expect(user.get("email") == EMAIL, f"email not stored as sent: {body}")
    expect(user.get("user_id"), f"missing user_id: {body}")
    expect(user.get("name") == "Smoke Tester", f"unexpected name: {body}")
    STATE["access_token"] = body["token"]
    STATE["user_id"] = user["user_id"]


def check_identity_register_normalizes_email() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={
            "email": f"UPPER_{RUN_ID}@Example.COM",
            "password": PASSWORD,
            "name": "Case Test",
        },
        timeout=30,
    )
    expect(response.status_code == 201, detail(response))
    email = (response.json().get("user") or {}).get("email")
    expect(email == f"upper_{RUN_ID}@example.com", f"email not lowercased: {email}")


def check_identity_register_duplicate() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "name": "Smoke Tester"},
        timeout=30,
    )
    expect(response.status_code == 409, f"expected 409, got {detail(response)}")


def check_identity_register_invalid_email() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={"email": "not-an-email", "password": PASSWORD, "name": "Smoke Tester"},
        timeout=30,
    )
    expect(response.status_code == 422, f"expected 422, got {detail(response)}")


def check_identity_register_short_password() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={
            "email": f"short_{RUN_ID}@example.com",
            "password": "123",
            "name": "Smoke Tester",
        },
        timeout=30,
    )
    expect(response.status_code == 422, f"expected 422, got {detail(response)}")


def check_identity_register_missing_name() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/register",
        json={"email": f"noname_{RUN_ID}@example.com", "password": PASSWORD},
        timeout=30,
    )
    expect(response.status_code == 422, f"expected 422, got {detail(response)}")


def check_identity_login_ok() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    expect(body.get("token"), f"missing token: {body}")
    expect(
        (body.get("user") or {}).get("user_id") == STATE.get("user_id"),
        f"user mismatch: {body}",
    )
    STATE["access_token"] = body["token"]


def check_identity_login_wrong_password() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/login",
        json={"email": EMAIL, "password": "WrongPass!123"},
        timeout=30,
    )
    expect(response.status_code == 401, f"expected 401, got {detail(response)}")


def check_identity_login_unknown_user() -> None:
    response = requests.post(
        f"{IDENTITY_URL}/auth/login",
        json={"email": f"ghost_{RUN_ID}@example.com", "password": PASSWORD},
        timeout=30,
    )
    expect(response.status_code == 401, f"expected 401, got {detail(response)}")


def check_identity_me() -> None:
    response = requests.get(
        f"{IDENTITY_URL}/auth/me",
        headers={"Authorization": f"Bearer {STATE['access_token']}"},
        timeout=30,
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    expect(body.get("email") == EMAIL, f"unexpected profile: {body}")
    expect(body.get("user_id") == STATE["user_id"], f"user_id mismatch: {body}")


def check_identity_me_unauthenticated() -> None:
    response = requests.get(f"{IDENTITY_URL}/auth/me", timeout=30)
    expect(response.status_code == 401, f"expected 401, got {detail(response)}")


def check_identity_me_bad_token() -> None:
    response = requests.get(
        f"{IDENTITY_URL}/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        timeout=30,
    )
    expect(response.status_code == 401, f"expected 401, got {detail(response)}")


def check_identity_me_gateway_header() -> None:
    """Gateway-injected X-User-Id is trusted: real id -> 200, bogus id -> 404."""
    ok = requests.get(
        f"{IDENTITY_URL}/auth/me", headers={"X-User-Id": STATE["user_id"]}, timeout=30
    )
    expect(ok.status_code == 200, f"X-User-Id path failed: {detail(ok)}")
    bogus = requests.get(
        f"{IDENTITY_URL}/auth/me", headers={"X-User-Id": "does-not-exist"}, timeout=30
    )
    expect(bogus.status_code == 404, f"expected 404, got {detail(bogus)}")


IDENTITY_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("identity: GET /health", check_identity_health),
    ("identity: register -> 201 token + profile", check_identity_register),
    ("identity: register lowercases email", check_identity_register_normalizes_email),
    ("identity: duplicate register -> 409", check_identity_register_duplicate),
    ("identity: invalid email -> 422", check_identity_register_invalid_email),
    ("identity: short password -> 422", check_identity_register_short_password),
    ("identity: missing name -> 422", check_identity_register_missing_name),
    ("identity: login -> 200 token", check_identity_login_ok),
    ("identity: wrong password -> 401", check_identity_login_wrong_password),
    ("identity: unknown email -> 401", check_identity_login_unknown_user),
    ("identity: GET /me with Bearer", check_identity_me),
    ("identity: GET /me without auth -> 401", check_identity_me_unauthenticated),
    ("identity: GET /me with bad JWT -> 401", check_identity_me_bad_token),
    ("identity: GET /me via X-User-Id (200 / 404)", check_identity_me_gateway_header),
]


def state_id(key: str) -> str:
    """Read an id recorded by an earlier check, failing with a clear reason."""
    value = STATE.get(key)
    if not value:
        raise AssertionError(
            f"prerequisite missing: {key} (an earlier check did not record it)"
        )
    return value


def remember_created(booking_id: str, owner: str) -> str:
    """Track a created booking (with its owner) so the run can cancel it afterwards."""
    STATE.setdefault("created_bookings", []).append((booking_id, owner))
    return booking_id


def slot_is_free(start: datetime, end: datetime, user_id: str = "smoke-probe") -> bool:
    """Ask the booking service whether the smoke room is free."""
    response = requests.get(
        f"{BOOKING_API}/check",
        params={
            "room": SMOKE_ROOM,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "user_id": user_id,
        },
        headers=internal_headers(),
        timeout=30,
    )
    if response.status_code != 200:
        return False
    return bool(response.json().get("available"))


def resolve_free_slots() -> None:
    """Point the slot globals at the first free 2-hour window from tomorrow 08:00."""
    global TOMORROW, SLOT_END, ADJACENT_START, ADJACENT_END
    base = (datetime.now() + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    for step in range(24):
        candidate = base + timedelta(minutes=30 * step)
        end = candidate + timedelta(minutes=60)
        adjacent_end = end + timedelta(minutes=60)
        if slot_is_free(candidate, end) and slot_is_free(end, adjacent_end):
            TOMORROW, SLOT_END = candidate, end
            ADJACENT_START, ADJACENT_END = end, adjacent_end
            print(
                f"  ℹ️  using free {SMOKE_ROOM} window {TOMORROW:%Y-%m-%d %H:%M} - {ADJACENT_END:%H:%M}"
            )
            return
    print("  ⚠️  no free 2-hour window found, falling back to the default slot")


# ---------------------------------------------------------------
# 2. Booking service (business rules: catalog, overlap, cancel)
# ---------------------------------------------------------------
BOOKING_API = f"{BOOKING_URL}/api/business/bookings"


def booking_payload(
    user_id: str, room: str, start: datetime, end: datetime, purpose: str
) -> dict:
    """Build a BookingCreate payload."""
    return {
        "user_id": user_id,
        "room": room,
        "purpose": purpose,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
    }


def check_booking_health() -> None:
    response = requests.get(f"{BOOKING_URL}/health", timeout=15)
    expect(response.status_code == 200, detail(response))


def check_booking_requires_token() -> None:
    response = requests.get(f"{BOOKING_API}/rooms", timeout=15)
    expect(
        response.status_code == 401,
        f"expected 401 without token, got {detail(response)}",
    )
    bad = requests.get(
        f"{BOOKING_API}/rooms", headers={"X-Internal-Token": "wrong"}, timeout=15
    )
    expect(bad.status_code == 401, f"expected 401 with wrong token, got {detail(bad)}")


def check_booking_rooms_catalog() -> None:
    response = requests.get(
        f"{BOOKING_API}/rooms", headers=internal_headers(), timeout=15
    )
    expect(response.status_code == 200, detail(response))
    catalog = response.json()
    expect(len(catalog) == 24, f"expected 24 illustrative rooms: {catalog}")
    room = catalog.get(SMOKE_ROOM) or {}
    expect(room.get("site_code") == "GD3", f"unexpected site: {room}")
    expect(room.get("room_type") == "MEETING", f"unexpected type: {room}")
    expect(room.get("capacity") == 16, f"unexpected capacity: {room}")
    expect(room.get("status") == "ACTIVE", f"unexpected status: {room}")
    expect(
        "video conference" in room.get("equipment", []), f"unexpected equipment: {room}"
    )
    expect(
        room.get("source_status") == "illustrative", f"missing source warning: {room}"
    )


def check_booking_create() -> None:
    resolve_free_slots()
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER, SMOKE_ROOM, TOMORROW, SLOT_END, "Smoke test meeting"
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 201, detail(response))
    body = response.json()
    expect(str(body.get("booking_id", "")).startswith("bk-"), f"unexpected id: {body}")
    expect(body.get("user_id") == BOOKING_USER, f"owner mismatch: {body}")
    expect(body.get("room") == SMOKE_ROOM, f"room mismatch: {body}")
    expect(
        body.get("status") == "confirmed",
        f"expected confirmed, got {body.get('status')}",
    )
    STATE["booking_id"] = remember_created(body["booking_id"], BOOKING_USER)


def check_booking_availability_conflict() -> None:
    params = {
        "room": SMOKE_ROOM,
        "start_at": TOMORROW.isoformat(),
        "end_at": SLOT_END.isoformat(),
        "user_id": BOOKING_USER,
    }
    response = requests.get(
        f"{BOOKING_API}/check", params=params, headers=internal_headers(), timeout=30
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    expect(body.get("available") is False, f"slot should be taken: {body}")
    expect(body.get("own_conflict") is True, f"should be own conflict: {body}")
    expect(
        (body.get("conflict") or {}).get("booking_id") == state_id("booking_id"),
        f"conflict mismatch: {body}",
    )


def check_booking_overlap_same_user() -> None:
    shifted = booking_payload(
        BOOKING_USER,
        SMOKE_ROOM,
        TOMORROW + timedelta(minutes=30),
        SLOT_END + timedelta(minutes=30),
        "Overlap own",
    )
    response = requests.post(
        BOOKING_API, json=shifted, headers=internal_headers(), timeout=30
    )
    expect(response.status_code == 409, f"expected 409, got {detail(response)}")


def check_booking_overlap_other_user() -> None:
    other = booking_payload(
        f"smoke-other-{RUN_ID}",
        SMOKE_ROOM,
        TOMORROW,
        SLOT_END,
        "Overlap by someone else",
    )
    response = requests.post(
        BOOKING_API, json=other, headers=internal_headers(), timeout=30
    )
    if response.status_code == 201:
        # Should not happen (the slot is taken); register it so cleanup frees it again.
        remember_created(response.json()["booking_id"], other["user_id"])
    expect(response.status_code == 409, f"expected 409, got {detail(response)}")


def check_booking_adjacent_slot_allowed() -> None:
    """end_at == next start_at is NOT an overlap (half-open interval)."""
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER, SMOKE_ROOM, ADJACENT_START, ADJACENT_END, "Adjacent meeting"
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 201, detail(response))
    STATE["adjacent_booking_id"] = remember_created(
        response.json()["booking_id"], BOOKING_USER
    )


def check_booking_unknown_room() -> None:
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER,
            "UNKNOWN-999",
            TOMORROW + timedelta(hours=3),
            SLOT_END + timedelta(hours=3),
            "Bad room",
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 400, f"expected 400, got {detail(response)}")


def check_booking_end_before_start() -> None:
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER, "HL-C201", SLOT_END, TOMORROW, "Reversed window"
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 400, f"expected 400, got {detail(response)}")


def check_booking_past_time() -> None:
    past_start = datetime.now() - timedelta(days=1)
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER,
            "HL-C201",
            past_start,
            past_start + timedelta(hours=1),
            "In the past",
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 400, f"expected 400, got {detail(response)}")


def check_booking_short_purpose() -> None:
    response = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER,
            "HL-C201",
            TOMORROW + timedelta(hours=5),
            SLOT_END + timedelta(hours=5),
            "ab",
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 422, f"expected 422, got {detail(response)}")


def check_booking_list_and_get() -> None:
    listing = requests.get(
        f"{BOOKING_API}",
        params={"user_id": BOOKING_USER},
        headers=internal_headers(),
        timeout=30,
    )
    expect(listing.status_code == 200, detail(listing))
    ids = [item["booking_id"] for item in listing.json()]
    expect(state_id("booking_id") in ids, f"created booking missing from list: {ids}")
    expect(
        state_id("adjacent_booking_id") in ids,
        f"adjacent booking missing from list: {ids}",
    )

    single = requests.get(
        f"{BOOKING_API}/{state_id('booking_id')}",
        headers=booking_headers(BOOKING_USER),
        timeout=30,
    )
    expect(single.status_code == 200, detail(single))
    expect(single.json()["room"] == SMOKE_ROOM, f"unexpected booking: {single.json()}")

    missing = requests.get(
        f"{BOOKING_API}/bk-doesnotexist",
        headers=booking_headers(BOOKING_USER),
        timeout=30,
    )
    expect(missing.status_code == 404, f"expected 404, got {detail(missing)}")


def check_booking_update_purpose() -> None:
    response = requests.patch(
        f"{BOOKING_API}/{state_id('booking_id')}",
        json={"purpose": "Smoke test meeting (renamed)"},
        headers=booking_headers(BOOKING_USER),
        timeout=30,
    )
    expect(response.status_code == 200, detail(response))
    expect(
        response.json()["purpose"] == "Smoke test meeting (renamed)",
        f"not updated: {response.json()}",
    )


def check_booking_reschedule_into_conflict() -> None:
    """Moving a booking onto the adjacent booking's slot must be rejected."""
    response = requests.patch(
        f"{BOOKING_API}/{state_id('booking_id')}",
        json={
            "start_at": ADJACENT_START.isoformat(),
            "end_at": ADJACENT_END.isoformat(),
        },
        headers=booking_headers(BOOKING_USER),
        timeout=30,
    )
    expect(response.status_code == 409, f"expected 409, got {detail(response)}")


def check_booking_cancel_foreign() -> None:
    response = requests.delete(
        f"{BOOKING_API}/{state_id('adjacent_booking_id')}",
        params={"user_id": f"smoke-intruder-{RUN_ID}"},
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 403, f"expected 403, got {detail(response)}")


def check_booking_cancel_unknown() -> None:
    response = requests.delete(
        f"{BOOKING_API}/bk-doesnotexist",
        params={"user_id": BOOKING_USER},
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 404, f"expected 404, got {detail(response)}")


def check_booking_cancel_and_frees_slot() -> None:
    """Owner cancel -> 200, status flips to cancelled, slot becomes bookable again."""
    cancelled = requests.delete(
        f"{BOOKING_API}/{state_id('booking_id')}",
        params={"user_id": BOOKING_USER},
        headers=internal_headers(),
        timeout=30,
    )
    expect(cancelled.status_code == 200, detail(cancelled))
    expect(
        cancelled.json().get("booking_id") == state_id("booking_id"),
        f"unexpected body: {cancelled.json()}",
    )

    fetched = requests.get(
        f"{BOOKING_API}/{state_id('booking_id')}",
        headers=booking_headers(BOOKING_USER),
        timeout=30,
    )
    expect(fetched.status_code == 200, detail(fetched))
    expect(
        fetched.json()["status"] == "cancelled",
        f"status not cancelled: {fetched.json()}",
    )

    again = requests.delete(
        f"{BOOKING_API}/{state_id('booking_id')}",
        params={"user_id": BOOKING_USER},
        headers=internal_headers(),
        timeout=30,
    )
    expect(
        again.status_code == 400, f"expected 400 on double cancel, got {detail(again)}"
    )

    rebooked = requests.post(
        BOOKING_API,
        json=booking_payload(
            BOOKING_USER, SMOKE_ROOM, TOMORROW, SLOT_END, "Rebooked after cancel"
        ),
        headers=internal_headers(),
        timeout=30,
    )
    expect(
        rebooked.status_code == 201,
        f"cancelled slot should be free: {detail(rebooked)}",
    )
    STATE["rebooked_id"] = remember_created(rebooked.json()["booking_id"], BOOKING_USER)


BOOKING_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("booking: GET /health", check_booking_health),
    ("booking: routes require X-Internal-Token", check_booking_requires_token),
    (
        "booking: UET room catalog (24 rooms + operational fields)",
        check_booking_rooms_catalog,
    ),
    ("booking: create -> 201 confirmed", check_booking_create),
    ("booking: GET /check reports own conflict", check_booking_availability_conflict),
    ("booking: overlapping slot same user -> 409", check_booking_overlap_same_user),
    ("booking: overlapping slot other user -> 409", check_booking_overlap_other_user),
    (
        "booking: adjacent slot (end == start) -> 201",
        check_booking_adjacent_slot_allowed,
    ),
    ("booking: unknown room -> 400", check_booking_unknown_room),
    ("booking: end_at before start_at -> 400", check_booking_end_before_start),
    ("booking: start_at in the past -> 400", check_booking_past_time),
    ("booking: purpose too short -> 422", check_booking_short_purpose),
    ("booking: list by user + get by id + 404", check_booking_list_and_get),
    ("booking: PATCH purpose -> 200", check_booking_update_purpose),
    (
        "booking: reschedule into conflict -> 409",
        check_booking_reschedule_into_conflict,
    ),
    ("booking: cancel foreign booking -> 403", check_booking_cancel_foreign),
    ("booking: cancel unknown id -> 404", check_booking_cancel_unknown),
    (
        "booking: cancel frees the slot (+ double cancel 400)",
        check_booking_cancel_and_frees_slot,
    ),
]


# ---------------------------------------------------------------
# 3. Conversation service (persistence + sync semantics + memory)
# ---------------------------------------------------------------
CONV_PUBLIC = f"{CONVERSATION_URL}/conversations"
CONV_INTERNAL = f"{CONVERSATION_URL}/internal/conversations"
SYNC_ID = f"smoke-sync-{RUN_ID}"
SYNC_USER = f"smoke-user-{RUN_ID}"


def sync_payload(messages: list[dict]) -> dict:
    """Build a SyncMessagesRequest body for the internal sync endpoint."""
    return {
        "messages": messages,
        "user_id": SYNC_USER,
        "title": "Smoke sync conversation",
    }


def put_sync(
    conversation_id: str, payload: dict, headers: dict[str, str] | None = None
) -> requests.Response:
    """PUT the internal sync endpoint."""
    return requests.put(
        f"{CONV_INTERNAL}/{conversation_id}/messages",
        json=payload,
        headers=conversation_headers() if headers is None else headers,
        timeout=60,
    )


def check_conversation_health() -> None:
    response = requests.get(f"{CONVERSATION_URL}/health", timeout=15)
    expect(response.status_code == 200, detail(response))


def check_conversation_internal_requires_token() -> None:
    response = put_sync(
        SYNC_ID, sync_payload([{"role": "user", "content": "hi"}]), headers={}
    )
    expect(
        response.status_code == 401,
        f"expected 401 without token, got {detail(response)}",
    )
    bad = put_sync(
        SYNC_ID,
        sync_payload([{"role": "user", "content": "hi"}]),
        headers={"X-Internal-Api-Token": "wrong"},
    )
    expect(bad.status_code == 401, f"expected 401 with wrong token, got {detail(bad)}")


def check_conversation_sync_autocreate_append() -> None:
    """First sync auto-creates the conversation row and appends the messages."""
    response = put_sync(
        SYNC_ID,
        sync_payload(
            [
                {"role": "user", "content": "Chao ban"},
                {"role": "assistant", "content": "Chao ban, minh giup duoc gi?"},
            ]
        ),
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    expect(body.get("action") == "append", f"expected append, got {body}")
    expect(body.get("message_count") == 2, f"expected 2 messages, got {body}")

    header = requests.get(
        f"{CONV_PUBLIC}/{SYNC_ID}", headers=conv_user_headers(SYNC_USER), timeout=30
    )
    expect(
        header.status_code == 200, f"conversation not auto-created: {detail(header)}"
    )
    expect(
        header.json().get("user_id") == SYNC_USER, f"owner mismatch: {header.json()}"
    )


def check_conversation_sync_skip() -> None:
    response = put_sync(
        SYNC_ID,
        sync_payload(
            [
                {"role": "user", "content": "Chao ban"},
                {"role": "assistant", "content": "Chao ban, minh giup duoc gi?"},
            ]
        ),
    )
    expect(response.status_code == 200, detail(response))
    expect(
        response.json().get("action") == "skip", f"expected skip, got {response.json()}"
    )


def check_conversation_sync_append_tail() -> None:
    response = put_sync(
        SYNC_ID,
        sync_payload(
            [
                {"role": "user", "content": "Chao ban"},
                {"role": "assistant", "content": "Chao ban, minh giup duoc gi?"},
                {"role": "user", "content": "Chinh sach nghi phep the nao?"},
                {"role": "assistant", "content": "Ban co 12 ngay phep nam."},
            ]
        ),
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    expect(body.get("action") == "append", f"expected append, got {body}")
    expect(body.get("message_count") == 4, f"expected 4 messages, got {body}")

    stored = requests.get(
        f"{CONV_PUBLIC}/{SYNC_ID}/messages",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(stored.status_code == 200, detail(stored))
    expect(len(stored.json()) == 4, f"expected 4 stored rows, got {len(stored.json())}")


def check_conversation_sync_replace() -> None:
    """A diverging (non-prefix) thread rewrites the stored history."""
    response = put_sync(
        SYNC_ID,
        sync_payload(
            [
                {"role": "user", "content": "Lich su moi hoan toan"},
                {"role": "assistant", "content": "Da cap nhat."},
            ]
        ),
    )
    expect(response.status_code == 200, detail(response))
    expect(
        response.json().get("action") == "replace",
        f"expected replace, got {response.json()}",
    )

    stored = requests.get(
        f"{CONV_PUBLIC}/{SYNC_ID}/messages",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(stored.status_code == 200, detail(stored))
    contents = [item["content"] for item in stored.json()]
    expect(
        contents == ["Lich su moi hoan toan", "Da cap nhat."],
        f"replace did not rewrite: {contents}",
    )
    roles = [item["role"] for item in stored.json()]
    expect(roles == ["user", "assistant"], f"unexpected roles: {roles}")


def check_conversation_crud_and_listing() -> None:
    created = requests.post(
        CONV_PUBLIC,
        json={"user_id": SYNC_USER, "title": "Smoke created conversation"},
        timeout=30,
    )
    expect(created.status_code == 201, detail(created))
    conversation_id = created.json()["conversation_id"]
    expect(
        created.json()["title"] == "Smoke created conversation",
        f"title not stored: {created.json()}",
    )

    listing = requests.get(CONV_PUBLIC, params={"user_id": SYNC_USER}, timeout=30)
    expect(listing.status_code == 200, detail(listing))
    ids = [item["conversation_id"] for item in listing.json()]
    expect(conversation_id in ids, f"created conversation missing from list: {ids}")
    expect(SYNC_ID in ids, f"synced conversation missing from list: {ids}")

    unknown = requests.get(
        f"{CONV_PUBLIC}/does-not-exist-{RUN_ID}",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(unknown.status_code == 404, f"expected 404, got {detail(unknown)}")
    unknown_messages = requests.get(
        f"{CONV_PUBLIC}/does-not-exist-{RUN_ID}/messages",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(
        unknown_messages.status_code == 404,
        f"expected 404, got {detail(unknown_messages)}",
    )

    deleted = requests.delete(
        f"{CONV_PUBLIC}/{conversation_id}",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(deleted.status_code == 200, detail(deleted))
    after = requests.get(
        f"{CONV_PUBLIC}/{conversation_id}",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(after.status_code == 404, f"expected 404 after delete, got {detail(after)}")
    again = requests.delete(
        f"{CONV_PUBLIC}/{conversation_id}",
        headers=conv_user_headers(SYNC_USER),
        timeout=30,
    )
    expect(
        again.status_code == 404, f"expected 404 on second delete, got {detail(again)}"
    )


def check_conversation_memory_context() -> None:
    response = requests.get(
        f"{CONV_INTERNAL}/{SYNC_ID}/memory",
        params={"user_id": SYNC_USER, "query": "dat phong hop"},
        headers=conversation_headers(),
        timeout=60,
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    # Independent-thread memory: only the current thread's own episode is
    # returned — there is no cross-thread episodic_memory_context anymore.
    expect("current_episode" in body, f"missing current_episode: {body}")
    expect(
        "episodic_memory_context" not in body,
        f"cross-thread memory should be gone: {body}",
    )

    missing_user = requests.get(
        f"{CONV_INTERNAL}/{SYNC_ID}/memory", headers=conversation_headers(), timeout=60
    )
    expect(
        missing_user.status_code == 422,
        f"expected 422 without user_id, got {detail(missing_user)}",
    )


CONVERSATION_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("conversation: GET /health", check_conversation_health),
    (
        "conversation: internal sync requires X-Internal-Api-Token",
        check_conversation_internal_requires_token,
    ),
    (
        "conversation: sync auto-creates + appends",
        check_conversation_sync_autocreate_append,
    ),
    ("conversation: identical sync -> skip", check_conversation_sync_skip),
    (
        "conversation: prefix sync -> append (tail only)",
        check_conversation_sync_append_tail,
    ),
    ("conversation: diverging sync -> replace", check_conversation_sync_replace),
    (
        "conversation: CRUD, listing, 404s, cascade delete",
        check_conversation_crud_and_listing,
    ),
    ("conversation: episodic memory context", check_conversation_memory_context),
]


# ---------------------------------------------------------------
# 4. RAG service (hybrid + HyDE + rerank + MMR + semantic cache)
# ---------------------------------------------------------------
RAG_QUERY = (
    "Ch\u00ednh s\u00e1ch ngh\u1ec9 ph\u00e9p n\u0103m c\u1ee7a nh\u00e2n vi\u00ean UET"
)


def check_rag_health() -> None:
    root = requests.get(f"{RAG_URL}/health", timeout=60)
    expect(root.status_code == 200, detail(root))
    kb = requests.get(f"{RAG_URL}/api/kb/health", timeout=60)
    expect(kb.status_code == 200, detail(kb))


def check_rag_search_returns_grounded_chunks() -> None:
    response = requests.post(
        f"{RAG_URL}/api/kb/search",
        json={"query": RAG_QUERY, "top_k": 3},
        headers=internal_headers(),
        timeout=TIMEOUT,
    )
    expect(response.status_code == 200, detail(response))
    body = response.json()
    results = body.get("results") or []
    expect(results, f"no chunks retrieved: {body}")
    expect(len(results) <= 3, f"top_k not honoured: {len(results)} results")
    for item in results:
        expect(str(item.get("text", "")).strip(), f"empty chunk text: {item}")
        expect("source" in item, f"missing source metadata: {item}")


def check_rag_search_semantic_cache() -> None:
    """The same query twice must be served from the semantic cache."""
    first = requests.post(
        f"{RAG_URL}/api/kb/search",
        json={"query": RAG_QUERY, "top_k": 3},
        headers=internal_headers(),
        timeout=TIMEOUT,
    )
    expect(first.status_code == 200, detail(first))
    second = requests.post(
        f"{RAG_URL}/api/kb/search",
        json={"query": RAG_QUERY, "top_k": 3},
        headers=internal_headers(),
        timeout=TIMEOUT,
    )
    expect(second.status_code == 200, detail(second))
    expect(
        second.json().get("cache_hit") is True,
        f"expected semantic cache hit: {second.json()}",
    )


def check_rag_search_validation() -> None:
    too_many = requests.post(
        f"{RAG_URL}/api/kb/search",
        json={"query": RAG_QUERY, "top_k": 100},
        headers=internal_headers(),
        timeout=60,
    )
    expect(
        too_many.status_code == 422,
        f"expected 422 for top_k=100, got {detail(too_many)}",
    )
    empty = requests.post(
        f"{RAG_URL}/api/kb/search",
        json={"query": "", "top_k": 3},
        headers=internal_headers(),
        timeout=60,
    )
    expect(
        empty.status_code == 422, f"expected 422 for empty query, got {detail(empty)}"
    )


def check_rag_cache_stats() -> None:
    response = requests.get(
        f"{RAG_URL}/api/kb/cache/stats", headers=internal_headers(), timeout=60
    )
    expect(response.status_code == 200, detail(response))
    stats = response.json()
    expect("hits" in stats and "misses" in stats, f"unexpected cache stats: {stats}")


RAG_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("rag: GET /health + /api/kb/health", check_rag_health),
    (
        "rag: search returns grounded chunks (top_k honoured)",
        check_rag_search_returns_grounded_chunks,
    ),
    ("rag: repeated query hits the semantic cache", check_rag_search_semantic_cache),
    ("rag: top_k / empty query validation -> 422", check_rag_search_validation),
    ("rag: GET /api/kb/cache/stats", check_rag_cache_stats),
]


# ---------------------------------------------------------------
# 5. Frontend (nginx static UI; assets fall back to disk when nginx is down)
# ---------------------------------------------------------------
FRONTEND_DIR = PROJECT_ROOT / "services" / "frontend" / "static"
CHAT_HOOKS = (
    "app-view",
    "chat-log",
    "chat-scroll",
    "chat-form",
    "chat-input",
    "send-btn",
    "stop-btn",
    "conversation-list",
    "new-chat-btn",
    "toast",
)
AUTH_HOOKS = (
    "auth-view",
    "auth-form",
    "auth-title",
    "auth-subtitle",
    "auth-name",
    "auth-email",
    "auth-password",
    "auth-submit",
    "auth-switch-btn",
    "auth-error",
    "guest-btn",
)
_FRONTEND_UP: bool | None = None


def frontend_up() -> bool:
    """Cache whether nginx is serving the UI (docker compose only)."""
    global _FRONTEND_UP
    if _FRONTEND_UP is None:
        _FRONTEND_UP = is_reachable(FRONTEND_URL)
        if not _FRONTEND_UP:
            print(
                f"  \u2139\ufe0f  nginx down at {FRONTEND_URL} \u2014 assets read from {FRONTEND_DIR}"
            )
    return _FRONTEND_UP


def frontend_asset(relative_path: str) -> str:
    """Fetch a static asset over HTTP when nginx is up, otherwise from disk."""
    if frontend_up():
        response = requests.get(f"{FRONTEND_URL}/{relative_path}", timeout=15)
        expect(response.status_code == 200, f"{relative_path} -> {detail(response)}")
        return response.text
    asset = FRONTEND_DIR / relative_path
    expect(asset.exists(), f"missing asset on disk: {asset}")
    return asset.read_text(encoding="utf-8")


def check_frontend_index() -> None:
    """index.html must expose every hook chat.js/auth.js rely on."""
    html = frontend_asset("index.html")
    for element_id in CHAT_HOOKS:
        expect(f'id="{element_id}"' in html, f"missing #{element_id} in index.html")
    for element_id in AUTH_HOOKS:
        expect(f'id="{element_id}"' in html, f"missing #{element_id} in index.html")
    for script in ("js/api.js", "js/chat.js", "js/auth.js", "js/app.js"):
        expect(script in html, f"index.html does not load {script}")


def check_frontend_assets() -> None:
    """The JS/CSS bundles must be served and non-trivial."""
    api_js = frontend_asset("js/api.js")
    expect("/api/chat/stream" in api_js, "api.js does not call /api/chat/stream")
    expect("/api/chat/resume" in api_js, "api.js does not call /api/chat/resume (HITL)")
    chat_js = frontend_asset("js/chat.js")
    for event in ("agent", "tool", "token", "context", "interrupt", "done"):
        expect(
            f'"{event}"' in chat_js or f"'{event}'" in chat_js,
            f"chat.js ignores SSE event '{event}'",
        )
    expect("/auth/login" in api_js, "api.js does not call /auth/login")
    expect("/auth/register" in api_js, "api.js does not call /auth/register")
    auth_js = frontend_asset("js/auth.js")
    expect(
        "identity.register" in auth_js and "identity.login" in auth_js,
        "auth.js does not drive login/register through the identity API helper",
    )
    css = frontend_asset("css/chat.css")
    expect(len(css) > 500, f"chat.css looks empty ({len(css)} chars)")


def check_frontend_leaks_no_internal_token() -> None:
    """Internal service tokens must never be shipped to the browser."""
    for asset in (
        "index.html",
        "js/api.js",
        "js/app.js",
        "js/chat.js",
        "js/auth.js",
        "js/runtime-config.js",
    ):
        body = frontend_asset(asset)
        expect("X-Internal-Token" not in body, f"{asset} leaks X-Internal-Token")
        expect(
            "X-Internal-Api-Token" not in body, f"{asset} leaks X-Internal-Api-Token"
        )
        expect(INTERNAL_TOKEN not in body, f"{asset} embeds the internal token value")


FRONTEND_CHECKS = [
    ("frontend: index.html exposes chat + auth hooks", check_frontend_index),
    ("frontend: js/css assets present and wired to SSE + auth", check_frontend_assets),
    (
        "frontend: no internal token leaks into browser assets",
        check_frontend_leaks_no_internal_token,
    ),
]


# ---------------------------------------------------------------
# 6. Agent service (LangGraph router + sub-agents + SSE + HITL)
# ---------------------------------------------------------------
AGENT_USER = f"smoke-agent-{RUN_ID}"
AGENT_APPROVE_ROOM = "GD3-402"
AGENT_REJECT_ROOM = "HL-C201"
# Resolved lazily by find_free_window(): the booking tool fast-fails on an
# occupied slot *before* asking for approval, so a row left over from an earlier
# run would turn the HITL check into a plain tool call.
AGENT_APPROVE_SLOT: datetime | None = None
AGENT_REJECT_SLOT: datetime | None = None
TERMINAL_EVENTS = {"done", "interrupt", "error"}


def find_free_window(room: str) -> datetime:
    """Return the start of the first free 1-hour window for `room` (from day+2, 09:00)."""
    base = (datetime.now() + timedelta(days=2)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    for day in range(3):
        for step in range(16):
            candidate = base + timedelta(days=day, minutes=30 * step)
            response = requests.get(
                f"{BOOKING_API}/check",
                params={
                    "room": room,
                    "start_at": candidate.isoformat(),
                    "end_at": (candidate + timedelta(minutes=60)).isoformat(),
                    "user_id": AGENT_USER,
                },
                headers=internal_headers(),
                timeout=30,
            )
            if response.status_code == 200 and response.json().get("available"):
                return candidate
    raise AssertionError(f"no free {room} window found in the next 3 days")


def slot_phrases(start: datetime) -> tuple[str, str, str]:
    """Build (user-facing time, ISO prefix, ISO date) for a resolved slot."""
    return (
        f"{start:%H:%M} ng\u00e0y {start:%d/%m/%Y}",
        f"{start:%Y-%m-%dT%H:%M}",
        f"{start:%Y-%m-%d}",
    )


def agent_headers() -> dict[str, str]:
    """Headers Kong would inject — accepted in both enforcement modes.

    With AGENT_REQUIRE_GATEWAY=true the agent requires X-Gateway-Token +
    X-User-Id (services/agent/auth.py); with false the headers are ignored.
    X-User-Id carries the same identity as the request body (AGENT_USER), so
    every identity assertion holds regardless of the enforcement mode.
    """
    return {
        "X-Gateway-Token": GATEWAY_SECRET,
        "X-User-Id": AGENT_USER,
        "X-User-Email": EMAIL,
    }


def stream_events(url: str, payload: dict) -> list[dict]:
    """POST an SSE endpoint and collect parsed events until a terminal one."""
    events: list[dict] = []
    with requests.post(
        url, json=payload, headers=agent_headers(), stream=True, timeout=TIMEOUT
    ) as response:
        expect(response.status_code == 200, f"{url} -> {detail(response)}")
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            event = json.loads(raw[len("data: ") :])
            events.append(event)
            if event.get("event") in TERMINAL_EVENTS:
                break
    return events


def chat_payload(thread_id: str, message: str) -> dict:
    """Build a /api/chat/stream body carrying the smoke-test identity."""
    return {
        "thread_id": thread_id,
        "message": message,
        "user_id": AGENT_USER,
        "email": EMAIL,
    }


def answer_of(events: list[dict]) -> str:
    """Concatenate the streamed token deltas."""
    return "".join(str(e.get("data", "")) for e in events if e.get("event") == "token")


def tool_names(events: list[dict]) -> list[str]:
    """Names of every tool event (start and end)."""
    return [
        (e.get("data") or {}).get("name", "")
        for e in events
        if e.get("event") == "tool"
    ]


def agent_names(events: list[dict]) -> list[str]:
    """Names of every router 'agent' event."""
    return [
        (e.get("data") or {}).get("name", "")
        for e in events
        if e.get("event") == "agent"
    ]


def assert_clean_turn(events: list[dict]) -> None:
    """A finished turn must stream an answer and end with 'done' (no error)."""
    kinds = [e.get("event") for e in events]
    expect(
        "error" not in kinds,
        f"stream error: {[e for e in events if e.get('event') == 'error']}",
    )
    expect(kinds[-1] in TERMINAL_EVENTS, f"stream did not terminate: {kinds}")
    expect(bool(answer_of(events).strip()), f"empty answer, events={kinds}")


def check_agent_health() -> None:
    response = requests.get(f"{AGENT_URL}/health", timeout=60)
    expect(response.status_code == 200, detail(response))


def check_agent_stream_validation() -> None:
    # Headers first: FastAPI resolves Depends(verify_gateway_request) BEFORE
    # body validation, so without them this returns 401 (not 422) when
    # AGENT_REQUIRE_GATEWAY=true.
    response = requests.post(
        f"{AGENT_URL}/api/chat/stream",
        json={"message": "hi"},
        headers=agent_headers(),
        timeout=60,
    )
    expect(
        response.status_code == 422,
        f"expected 422 without thread_id, got {detail(response)}",
    )


def check_agent_general_chat() -> None:
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream",
        chat_payload(
            f"smoke-general-{RUN_ID}", "Chao ban, gioi thieu ngan gon ve ban di."
        ),
    )
    assert_clean_turn(events)
    expect(
        "general_chat" in agent_names(events),
        f"expected general_chat router label: {agent_names(events)}",
    )
    expect(events[-1].get("event") == "done", f"expected done, got {events[-1]}")


def check_agent_faq_uses_rag_tool() -> None:
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream",
        chat_payload(
            f"smoke-faq-{RUN_ID}",
            "UET yeu cau gi khi dung AI cho quyet dinh co anh huong lon?",
        ),
    )
    assert_clean_turn(events)
    expect(
        "faq_agent" in agent_names(events), f"expected faq_agent: {agent_names(events)}"
    )
    expect(
        "search_uet_knowledge" in tool_names(events),
        f"FAQ tool not called: {tool_names(events)}",
    )
    expect(events[-1].get("event") == "done", f"expected done, got {events[-1]}")


def check_agent_web_search() -> None:
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream",
        chat_payload(
            f"smoke-web-{RUN_ID}", "Tin tuc cong nghe noi bat hom nay ve AI la gi?"
        ),
    )
    assert_clean_turn(events)
    expect(
        "search_agent" in agent_names(events),
        f"expected search_agent: {agent_names(events)}",
    )
    expect(
        "search_web" in tool_names(events),
        f"web search tool not called: {tool_names(events)}",
    )


def agent_user_bookings() -> list[dict]:
    """Read the smoke agent user's bookings straight from the Booking service."""
    response = requests.get(
        BOOKING_API,
        params={"user_id": AGENT_USER},
        headers=internal_headers(),
        timeout=30,
    )
    expect(response.status_code == 200, detail(response))
    return response.json()


def resume_payload(thread_id: str, approved: bool) -> dict:
    """Build a /api/chat/resume body (identity must be re-sent after interrupt)."""
    return {
        "thread_id": thread_id,
        "decision": {"approved": approved},
        "user_id": AGENT_USER,
        "email": EMAIL,
    }


def check_agent_booking_needs_missing_field() -> None:
    """Without a time the booking agent must ask, never call a tool."""
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream",
        chat_payload(
            f"smoke-missing-{RUN_ID}",
            "Toi muon dat phong HL-C201 de hop giao ban.",
        ),
    )
    assert_clean_turn(events)
    expect(
        "booking_agent" in agent_names(events),
        f"expected booking_agent: {agent_names(events)}",
    )
    expect(
        "book_meeting_room" not in tool_names(events),
        f"tool called with missing info: {tool_names(events)}",
    )
    expect(
        events[-1].get("event") == "done",
        f"expected done (no approval needed), got {events[-1]}",
    )


def check_agent_booking_interrupt_and_approve() -> None:
    """Approving the HITL card must write exactly one booking owned by the caller."""
    global AGENT_APPROVE_SLOT
    AGENT_APPROVE_SLOT = find_free_window(AGENT_APPROVE_ROOM)
    when, iso_prefix, iso_date = slot_phrases(AGENT_APPROVE_SLOT)
    end_prefix = f"{(AGENT_APPROVE_SLOT + timedelta(minutes=60)):%Y-%m-%dT%H:%M}"
    print(f"  \u2139\ufe0f  approve slot: {AGENT_APPROVE_ROOM} {iso_prefix}")

    thread = f"smoke-hitl-{RUN_ID}"
    message = (
        f"\u0110\u1eb7t ph\u00f2ng {AGENT_APPROVE_ROOM} l\u00fac {when} "
        f"\u0111\u1ec3 h\u1ecdp d\u1ef1 \u00e1n smoke test."
    )
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream", chat_payload(thread, message)
    )
    kinds = [e.get("event") for e in events]
    expect("error" not in kinds, f"stream error: {events}")
    expect(
        kinds[-1] == "interrupt",
        f"expected an HITL interrupt, got {kinds}; tool calls: {tool_names(events)}; "
        f"answer: {answer_of(events)[:200]}",
    )

    interrupt = events[-1].get("data") or {}
    expect(
        interrupt.get("action") == "book_room",
        f"unexpected interrupt payload: {interrupt}",
    )
    details = interrupt.get("details") or {}
    expect(details.get("room") == AGENT_APPROVE_ROOM, f"unexpected room: {details}")
    expect(
        str(details.get("time", "")).startswith(iso_date), f"unexpected time: {details}"
    )
    expect(
        details.get("user_id") == AGENT_USER, f"identity lost in interrupt: {details}"
    )

    before = {item["booking_id"] for item in agent_user_bookings()}

    resumed = stream_events(
        f"{AGENT_URL}/api/chat/resume", resume_payload(thread, True)
    )
    assert_clean_turn(resumed)
    expect(
        "book_meeting_room" in tool_names(resumed),
        f"tool not executed on approve: {tool_names(resumed)}",
    )
    expect(resumed[-1].get("event") == "done", f"expected done, got {resumed[-1]}")

    created = [
        item for item in agent_user_bookings() if item["booking_id"] not in before
    ]
    expect(len(created) == 1, f"expected exactly 1 persisted booking, got {created}")
    booking = created[0]
    # Record it for cleanup *before* the field assertions, so a mismatch can
    # never leave a confirmed booking behind and break the next run.
    STATE["agent_booking_id"] = remember_created(booking["booking_id"], AGENT_USER)
    expect(booking["room"] == AGENT_APPROVE_ROOM, f"wrong room persisted: {booking}")
    expect(
        booking["user_id"] == AGENT_USER, f"booking not owned by the caller: {booking}"
    )
    expect(booking["status"] == "confirmed", f"unexpected status: {booking}")
    expect(booking["start_at"].startswith(iso_prefix), f"wrong start_at: {booking}")
    expect(booking["end_at"].startswith(end_prefix), f"wrong end_at: {booking}")


def check_agent_booking_reject_writes_nothing() -> None:
    """Rejecting the HITL card must leave the database and the slot untouched."""
    global AGENT_REJECT_SLOT
    AGENT_REJECT_SLOT = find_free_window(AGENT_REJECT_ROOM)
    when, iso_prefix, _ = slot_phrases(AGENT_REJECT_SLOT)
    end_iso = (AGENT_REJECT_SLOT + timedelta(minutes=60)).isoformat()
    print(f"  \u2139\ufe0f  reject slot: {AGENT_REJECT_ROOM} {iso_prefix}")

    thread = f"smoke-reject-{RUN_ID}"
    message = (
        f"\u0110\u1eb7t ph\u00f2ng {AGENT_REJECT_ROOM} l\u00fac {when} "
        f"\u0111\u1ec3 t\u1ed5ng k\u1ebft qu\u00fd."
    )
    events = stream_events(
        f"{AGENT_URL}/api/chat/stream", chat_payload(thread, message)
    )
    kinds = [e.get("event") for e in events]
    expect(
        kinds[-1] == "interrupt",
        f"expected an HITL interrupt, got {kinds}; answer: {answer_of(events)[:200]}",
    )
    expect(
        (events[-1].get("data") or {}).get("action") == "book_room",
        f"unexpected payload: {events[-1]}",
    )

    before = {item["booking_id"] for item in agent_user_bookings()}
    resumed = stream_events(
        f"{AGENT_URL}/api/chat/resume", resume_payload(thread, False)
    )
    assert_clean_turn(resumed)
    expect(resumed[-1].get("event") == "done", f"expected done, got {resumed[-1]}")

    after = {item["booking_id"] for item in agent_user_bookings()}
    expect(
        after == before, f"reject must not persist anything, new ids: {after - before}"
    )

    probe = requests.get(
        f"{BOOKING_API}/check",
        params={
            "room": AGENT_REJECT_ROOM,
            "start_at": AGENT_REJECT_SLOT.isoformat(),
            "end_at": end_iso,
            "user_id": AGENT_USER,
        },
        headers=internal_headers(),
        timeout=30,
    )
    expect(probe.status_code == 200, detail(probe))
    expect(
        probe.json().get("available") is True,
        f"rejected slot must stay free: {probe.json()}",
    )


AGENT_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("agent: GET /health", check_agent_health),
    ("agent: /api/chat/stream without thread_id -> 422", check_agent_stream_validation),
    (
        "agent: general chat streams tokens + agent label + done",
        check_agent_general_chat,
    ),
    (
        "agent: FAQ routes to RAG tool search_uet_knowledge",
        check_agent_faq_uses_rag_tool,
    ),
    ("agent: news routes to Tavily tool search_web", check_agent_web_search),
    (
        "agent: booking with missing time asks instead of calling a tool",
        check_agent_booking_needs_missing_field,
    ),
    (
        "agent: HITL interrupt -> approve persists the booking",
        check_agent_booking_interrupt_and_approve,
    ),
    (
        "agent: HITL interrupt -> reject persists nothing",
        check_agent_booking_reject_writes_nothing,
    ),
]


# ---------------------------------------------------------------
# Runner
# ---------------------------------------------------------------
SKIPPED: list[str] = []
SECTIONS: list[tuple[str, str, list[tuple[str, Callable[[], None]]]]] = [
    ("identity", IDENTITY_URL, IDENTITY_CHECKS),
    ("booking", BOOKING_URL, BOOKING_CHECKS),
    ("conversation", CONVERSATION_URL, CONVERSATION_CHECKS),
    ("rag", RAG_URL, RAG_CHECKS),
    ("agent", AGENT_URL, AGENT_CHECKS),
    ("frontend", FRONTEND_URL, FRONTEND_CHECKS),
]


def is_reachable(base_url: str) -> bool:
    """Probe /health (or /) so a down service is reported as SKIP, not FAIL."""
    for path in ("/health", "/"):
        try:
            requests.get(f"{base_url}{path}", timeout=10)
            return True
        except requests.RequestException:
            continue
    return False


def cleanup_bookings() -> None:
    """Cancel every booking this run created so reruns start from a clean calendar."""
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for booking_id, owner in STATE.get("created_bookings", []):
        if booking_id in seen:
            continue
        seen.add(booking_id)
        targets.append((booking_id, owner))
    if not targets:
        return
    print("\nCleanup:")
    for booking_id, owner in targets:
        try:
            response = requests.delete(
                f"{BOOKING_API}/{booking_id}",
                params={"user_id": owner},
                headers=internal_headers(),
                timeout=30,
            )
            print(f"  cancelled {booking_id} ({owner}) -> {response.status_code}")
            if response.status_code == 400:
                print(f"    (already cancelled earlier in the run: {detail(response)})")
        except requests.RequestException as error:
            print(f"  could not cancel {booking_id}: {error}")


def main() -> int:
    """Run every enabled section and return the process exit code."""
    parser = argparse.ArgumentParser(
        description="Smoke-test all UET AI services end to end."
    )
    parser.add_argument(
        "--fast", action="store_true", help="Skip the LLM-driven agent section."
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=[name for name, _, _ in SECTIONS],
        help="Run only the given section(s); repeatable.",
    )
    args = parser.parse_args()

    print("UET AI stack smoke test")
    for name, base_url, _ in SECTIONS:
        print(f"  {name:<13} {base_url}")

    for name, base_url, checks in SECTIONS:
        if args.only and name not in args.only:
            continue
        if args.fast and name == "agent":
            SKIPPED.append(f"{name} (--fast)")
            print(f"\n=== {name} === SKIPPED (--fast)")
            continue
        section(name)
        # The frontend section falls back to reading assets from disk, so only
        # the HTTP services are skipped when they are down.
        if name != "frontend" and not is_reachable(base_url):
            SKIPPED.append(f"{name} (unreachable at {base_url})")
            print(
                f"  \u26a0\ufe0f  service unreachable at {base_url} \u2014 section skipped"
            )
            continue
        for check_name, check_fn in checks:
            run_check(check_name, check_fn)

    cleanup_bookings()

    total = len(PASSED) + len(FAILED)
    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}/{total}")
    if SKIPPED:
        print(f"SKIPPED: {', '.join(SKIPPED)}")
    if FAILED:
        print(f"FAILED {len(FAILED)}:")
        for failure in FAILED:
            print(f"  - {failure}")
        return 1
    print("All service checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
