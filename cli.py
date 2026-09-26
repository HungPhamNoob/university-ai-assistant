# ============================================
# cli.py
# ============================================
"""
Terminal client of the UET AI stack (agent + identity + booking + conversation).

Two modes:

1. Interactive REPL — ``python cli.py``: chat with the assistant and inspect the
   backing services through slash commands (``/help`` lists all of them).
2. One-shot — ``python cli.py <thread_id> <query>``: send ONE message and exit.
   ``scripts/run_all_queries.sh`` uses this mode and pipes ``yes y`` so the
   human-in-the-loop approvals are granted automatically.

Identity: ``/login`` stores the JWT in ``data/.cli_session.json``. While such a
session exists every chat request carries the REAL user_id, so bookings and
stored conversations belong to the logged-in user instead of an anonymous
fallback (bug already hit: bookings written under 'anonymous').
"""

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# .env must be read BEFORE the service URLs/tokens are resolved.
load_dotenv()

ROOT = Path(__file__).resolve().parent
SESSION_PATH = ROOT / "data" / ".cli_session.json"

AGENT_URL = os.getenv(
    "AGENT_SERVICE_URL", f"http://localhost:{os.getenv('AGENT_PORT', '8000')}"
)
IDENTITY_URL = os.getenv(
    "IDENTITY_SERVICE_URL", f"http://localhost:{os.getenv('IDENTITY_PORT', '8001')}"
)
BOOKING_URL = os.getenv(
    "BOOKING_SERVICE_URL", f"http://localhost:{os.getenv('BOOKING_PORT', '8003')}"
)
CONVERSATION_URL = os.getenv(
    "CONVERSATION_SERVICE_URL",
    f"http://localhost:{os.getenv('CONVERSATION_PORT', '8004')}",
)

# Shared secret for the internal endpoints (booking/conversation) — local only.
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "internal-secret-token")
# Fallback identity used when no one is logged in (eval scripts).
DEFAULT_USER_ID = os.getenv("CLI_USER_ID", "cli-user")
HTTP_TIMEOUT = float(os.getenv("CLI_TIMEOUT", "180"))

HELP_TEXT = """\
Commands:
  /register <email> <password> <name>   create an account (Identity service)
  /login <email> <password>             login, JWT saved to data/.cli_session.json
  /logout                               forget the local session
  /me                                   show my profile
  /rooms                                list meeting rooms + capacities (Booking)
  /bookings                             list my bookings (Booking)
  /conversations                        list my stored conversations (Conversation)
  /messages <conversation_id>           show one conversation's messages
  /new                                  start a fresh conversation thread
  /help                                 show this help
  exit | quit                           leave the REPL

Anything else is streamed to the agent. Booking/cancellation pause for your
approval (human-in-the-loop) before touching the database.
"""


# ---------------------------------------------------------------- session ----
def load_session() -> dict[str, Any]:
    """
    Read the persisted login session.

    Returns:
        Dict with the keys token/user_id/email/name; empty when not logged in
        or when the file is unreadable.
    """
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_session(session: dict[str, Any]) -> None:
    """
    Persist a session payload next to the other local data files.

    Args:
        session: Dict produced from an /auth/register or /auth/login response.
    """
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(
        json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def clear_session() -> None:
    """Delete the persisted session file, if any."""
    SESSION_PATH.unlink(missing_ok=True)


def session_user_id(session: dict[str, Any]) -> str:
    """
    Resolve the user_id to send to the agent.

    Args:
        session: Currently loaded session.

    Returns:
        The logged-in user id, or the shared CLI fallback user.
    """
    return str(session.get("user_id") or DEFAULT_USER_ID)


def auth_headers(session: dict[str, Any]) -> dict[str, str]:
    """
    Build the Authorization header of the logged-in user.

    Args:
        session: Currently loaded session.

    Returns:
        Dict with the Bearer header, empty when nobody is logged in.
    """
    token = session.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def internal_headers() -> dict[str, str]:
    """
    Build the header required by the internal service endpoints.

    Returns:
        Dict carrying the shared X-Internal-Token secret.
    """
    return {"X-Internal-Token": INTERNAL_API_TOKEN}


def _print_error(message: str) -> None:
    """Print a red-ish error line to stdout (kept plain for piped logs)."""
    print(f"❌ {message}")


def _detail(response: httpx.Response) -> str:
    """
    Extract a readable error message from a failed HTTP response.

    Args:
        response: The non-2xx response returned by a service.

    Returns:
        The FastAPI 'detail' when present, else status + raw body snippet.
    """
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("detail"):
            return f"HTTP {response.status_code}: {body['detail']}"
    except (json.JSONDecodeError, ValueError):
        pass
    return f"HTTP {response.status_code}: {response.text[:200]}"


def _session_from_auth(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten an AuthResponse ({token, user}) into the local session shape.

    Args:
        payload: Body returned by /auth/register or /auth/login.

    Returns:
        Dict with token/user_id/email/name.
    """
    user = payload.get("user") or {}
    return {
        "token": payload.get("token", ""),
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
    }


# ------------------------------------------------------- service commands ----
def cmd_register(args: list[str]) -> dict[str, Any] | None:
    """
    Create an account through the Identity service and store the session.

    Args:
        args: [email, password, name...] — the name may contain spaces.

    Returns:
        The saved session dict, or None when the call failed.
    """
    if len(args) < 3:
        _print_error("Usage: /register <email> <password> <name>")
        return None
    email, password, name = args[0], args[1], " ".join(args[2:])
    try:
        response = httpx.post(
            f"{IDENTITY_URL}/auth/register",
            json={"email": email, "password": password, "name": name},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Identity unreachable: {error}")
        return None
    if response.status_code != 201:
        _print_error(_detail(response))
        return None
    session = _session_from_auth(response.json())
    save_session(session)
    print(
        f"✅ Registered {session['email']} (user_id={session['user_id']}) — session saved."
    )
    return session


def cmd_login(args: list[str]) -> dict[str, Any] | None:
    """
    Login through the Identity service and store the returned JWT.

    Args:
        args: [email, password].

    Returns:
        The saved session dict, or None when the credentials were rejected.
    """
    if len(args) != 2:
        _print_error("Usage: /login <email> <password>")
        return None
    try:
        response = httpx.post(
            f"{IDENTITY_URL}/auth/login",
            json={"email": args[0], "password": args[1]},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Identity unreachable: {error}")
        return None
    if response.status_code != 200:
        _print_error(_detail(response))
        return None
    session = _session_from_auth(response.json())
    save_session(session)
    print(
        f"✅ Logged in as {session['name']} <{session['email']}> (user_id={session['user_id']})."
    )
    return session


def cmd_me(session: dict[str, Any]) -> None:
    """
    Print the profile of the logged-in user.

    Args:
        session: Currently loaded session (needs a valid token).
    """
    if not session.get("token"):
        _print_error("Not logged in. Use /register or /login first.")
        return
    try:
        response = httpx.get(
            f"{IDENTITY_URL}/auth/me",
            headers=auth_headers(session),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Identity unreachable: {error}")
        return
    if response.status_code != 200:
        _print_error(_detail(response))
        return
    profile = response.json()
    print(
        f"👤 {profile.get('name')} <{profile.get('email')}>\n"
        f"   user_id  : {profile.get('user_id')}\n"
        f"   created  : {profile.get('created_at')}"
    )


def cmd_rooms() -> None:
    """List the meeting-room catalog exposed by the Booking service."""
    try:
        response = httpx.get(
            f"{BOOKING_URL}/api/business/bookings/rooms",
            headers=internal_headers(),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Booking unreachable: {error}")
        return
    if response.status_code != 200:
        _print_error(_detail(response))
        return
    rooms = response.json()
    print("🏢 Meeting rooms (name: capacity):")
    for name, capacity in rooms.items():
        print(f"   - {name}: {capacity} seats")


def cmd_bookings(session: dict[str, Any]) -> None:
    """
    List the bookings owned by the current CLI user.

    Args:
        session: Currently loaded session (its user_id scopes the query).
    """
    user_id = session_user_id(session)
    try:
        response = httpx.get(
            f"{BOOKING_URL}/api/business/bookings",
            params={"user_id": user_id},
            headers=internal_headers(),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Booking unreachable: {error}")
        return
    if response.status_code != 200:
        _print_error(_detail(response))
        return
    bookings = response.json()
    if not bookings:
        print(f"📭 No bookings for user_id={user_id}.")
        return
    print(f"📅 {len(bookings)} booking(s) of user_id={user_id}:")
    for item in bookings:
        print(
            f"   - {item['booking_id']} | {item['room']} | "
            f"{item['start_at']} → {item['end_at']} | {item['status']} | {item['purpose']}"
        )


def cmd_conversations(session: dict[str, Any]) -> None:
    """
    List the conversations stored for the current CLI user.

    Args:
        session: Currently loaded session (its user_id scopes the query).
    """
    user_id = session_user_id(session)
    try:
        response = httpx.get(
            f"{CONVERSATION_URL}/conversations",
            params={"user_id": user_id},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Conversation unreachable: {error}")
        return
    if response.status_code != 200:
        _print_error(_detail(response))
        return
    conversations = response.json()
    if not conversations:
        print(f"📭 No stored conversations for user_id={user_id}.")
        return
    print(f"💬 {len(conversations)} conversation(s) of user_id={user_id}:")
    for item in conversations:
        summary = str(item.get("summary") or "").replace("\n", " ")
        if len(summary) > 60:
            summary = summary[:57] + "..."
        print(
            f"   - {item.get('conversation_id')} | {item.get('title') or '(untitled)'} | "
            f"updated={item.get('updated_at')}\n     summary: {summary or '(none)'}"
        )


def cmd_messages(args: list[str]) -> None:
    """
    Print the stored messages of one conversation.

    Args:
        args: [conversation_id].
    """
    if not args:
        _print_error("Usage: /messages <conversation_id>")
        return
    conversation_id = args[0]
    try:
        response = httpx.get(
            f"{CONVERSATION_URL}/conversations/{conversation_id}/messages",
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as error:
        _print_error(f"Conversation unreachable: {error}")
        return
    if response.status_code != 200:
        _print_error(_detail(response))
        return
    messages = response.json()
    if not messages:
        print(f"📭 Conversation {conversation_id} has no messages.")
        return
    print(f"🧾 {len(messages)} message(s) of {conversation_id}:")
    for item in messages:
        role = str(item.get("role", "?")).upper()
        content = str(item.get("content", "")).replace("\n", " ")
        print(f"   [{role}] {content}")


# ------------------------------------------------------------- streaming ----
def ask_approval() -> bool:
    """
    Ask the human whether a sensitive tool call may run (HITL).

    Returns:
        True for 'y'/'yes'; False otherwise. A closed stdin (piped eval runs
        that exhausted their input) counts as a rejection so nothing is ever
        written to the database without an explicit yes.
    """
    try:
        answer = input("Approve? (y/n): ").strip().lower()
    except EOFError:
        print("n  (stdin closed → auto-reject)")
        return False
    return answer in ("y", "yes")


def consume_sse(
    client: httpx.Client, url: str, payload: dict[str, Any], session: dict[str, Any]
) -> str:
    """
    POST one chat/resume payload and render its SSE stream on stdout.

    Every event is surfaced so the terminal shows the same transparency as the
    web UI: which subagent answered, which tool ran, and every HITL pause.

    Args:
        client: Shared httpx client.
        url: /api/chat/stream or /api/chat/resume endpoint.
        payload: Request body (message or decision).
        session: Logged-in session, used for the Bearer header.

    Returns:
        'done' when the turn finished, 'interrupt' when the graph paused for a
        human decision, 'error' on a stream/HTTP failure.
    """
    try:
        with client.stream(
            "POST", url, json=payload, headers=auth_headers(session)
        ) as response:
            if response.status_code != 200:
                response.read()
                _print_error(_detail(response))
                if response.status_code == 401 and not session.get("token"):
                    _print_error(
                        "Chưa đăng nhập — chạy /login <email> <password> trước "
                        "(AGENT_SERVICE_URL trỏ Kong gateway, Kong yêu cầu JWT)."
                    )
                return "error"
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                event = data.get("event")
                if event == "token":
                    print(data.get("data", ""), end="", flush=True)
                elif event == "agent":
                    info = data.get("data") or {}
                    label = info.get("label") or info.get("name") or "agent"
                    print(f"\n→ [{label}]", flush=True)
                elif event == "tool":
                    tool = data.get("data") or {}
                    status = tool.get("status", "start")
                    icon = "🔧" if status == "start" else "✔️ "
                    print(
                        f"\n{icon} tool {tool.get('name', '?')} [{status}]", flush=True
                    )
                elif event == "context":
                    # Context-engineering transparency (what assembly did this
                    # turn). One line prefixed with an arrow for log filtering
                    # it out of the extracted answer text.
                    report = data.get("data") or {}
                    notes = []
                    if report.get("memory_injected"):
                        notes.append("ký ức cuộc trò chuyện đã inject")
                    if report.get("history_trimmed"):
                        notes.append(
                            f"lịch sử cắt {report.get('history_messages_in')}"
                            f"→{report.get('history_messages_out')} tin"
                        )
                    if report.get("tool_outputs_capped"):
                        notes.append(
                            f"cắt gọn {report['tool_outputs_capped']} tool output"
                        )
                    if report.get("system_over_budget"):
                        notes.append("system prompt vượt budget (giữ nguyên)")
                    if notes:
                        print(f"\n→ 🧠 context: {' · '.join(notes)}", flush=True)
                elif event == "interrupt":
                    details = data.get("data") or {}
                    message = details.get("message") or json.dumps(
                        details, ensure_ascii=False
                    )
                    print(f"\n⚠️  HITL REQUIRED: {message}")
                    return "interrupt"
                elif event == "error":
                    print(f"\n❌ Error: {data.get('data', 'unknown error')}")
                    return "error"
                elif event == "done":
                    print()
                    return "done"
    except httpx.HTTPError as error:
        _print_error(f"Agent unreachable: {error}")
        return "error"
    print()
    return "error"


def send_message(
    client: httpx.Client, thread_id: str, message: str, session: dict[str, Any]
) -> int:
    """
    Send one user message and stream the answer, resolving every HITL pause.

    The same user_id/email is carried into the resume call: after an interrupt
    the graph resumes with a fresh config, and a missing identity would make
    the booking tools write under the wrong owner.

    Args:
        client: Shared httpx client.
        thread_id: Conversation thread to append the turn to.
        message: User text.
        session: Logged-in session (empty dict when anonymous).

    Returns:
        Exit code: 0 when the turn completed, 1 on error.
    """
    user_id = session_user_id(session)
    email = session.get("email") or None
    url = f"{AGENT_URL}/api/chat/stream"
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "message": message,
        "user_id": user_id,
        "email": email,
    }

    while True:
        status = consume_sse(client, url, payload, session)
        if status != "interrupt":
            return 0 if status == "done" else 1
        approved = ask_approval()
        url = f"{AGENT_URL}/api/chat/resume"
        payload = {
            "thread_id": thread_id,
            "decision": {"approved": approved},
            "user_id": user_id,
            "email": email,
        }


# ------------------------------------------------------------------- REPL ----
def new_thread_id() -> str:
    """
    Generate a fresh conversation thread id.

    Returns:
        Id like 'cli-1a2b3c4d'.
    """
    return f"cli-{uuid.uuid4().hex[:8]}"


def handle_command(line: str, state: dict[str, Any]) -> None:
    """
    Execute one slash command, mutating the REPL state in place.

    Args:
        line: Raw user input starting with '/'.
        state: Mutable state holding 'session' and 'thread_id'.
    """
    parts = line.strip().split()
    command, args = parts[0].lower(), parts[1:]

    if command == "/help":
        print(HELP_TEXT)
    elif command == "/register":
        session = cmd_register(args)
        if session:
            state["session"] = session
            state["thread_id"] = new_thread_id()
    elif command == "/login":
        session = cmd_login(args)
        if session:
            state["session"] = session
            # A new identity must not inherit the previous user's thread.
            state["thread_id"] = new_thread_id()
    elif command == "/logout":
        clear_session()
        state["session"] = {}
        print(f"👋 Session cleared (back to user_id={DEFAULT_USER_ID}).")
    elif command == "/me":
        cmd_me(state["session"])
    elif command == "/rooms":
        cmd_rooms()
    elif command == "/bookings":
        cmd_bookings(state["session"])
    elif command == "/conversations":
        cmd_conversations(state["session"])
    elif command == "/messages":
        cmd_messages(args)
    elif command == "/new":
        state["thread_id"] = new_thread_id()
        print(f"🆕 New thread: {state['thread_id']}")
    else:
        _print_error(f"Unknown command '{command}'. Type /help for the list.")


def repl(thread_id: str) -> None:
    """
    Interactive chat loop.

    Args:
        thread_id: Thread used for the first turn.
    """
    state: dict[str, Any] = {"session": load_session(), "thread_id": thread_id}
    who = state["session"].get("email") or f"anonymous ({DEFAULT_USER_ID})"
    print(f"UET AI Chat CLI | thread={thread_id} | user={who}")
    print("Type /help for commands, 'exit' to quit\n")

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Bye!")
                break
            if user_input.startswith("/"):
                handle_command(user_input, state)
                continue
            send_message(client, state["thread_id"], user_input, state["session"])


def main() -> int:
    """
    Entry point: one-shot mode with >=2 args, interactive REPL otherwise.

    One-shot usage (used by scripts/run_all_queries.sh):
        python cli.py <thread_id> <query>

    Returns:
        Process exit code — 0 on success, 1 when the turn failed.
    """
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        print(HELP_TEXT)
        return 0

    session = load_session()

    if len(args) >= 2:
        thread_id, message = args[0], " ".join(args[1:])
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            return send_message(client, thread_id, message, session)

    repl(args[0] if len(args) == 1 else new_thread_id())
    return 0


if __name__ == "__main__":
    sys.exit(main())


r"""
uv run scripts/local.sh

docker exec -it configs-postgres-1 psql -U admin -d uet_ai_db

\dt                          -- liệt kê bảng
SELECT * FROM bookings;      -- xem các lịch đặt phòng
SELECT * FROM users;         -- user đã register
SELECT * FROM conversations; -- hội thoại
\q                           -- thoát



set -a && source .env && set +a
kill $(lsof -t -i:8000) 2>/dev/null; kill $(lsof -t -i:8001) 2>/dev/null
kill $(lsof -t -i:8002) 2>/dev/null; kill $(lsof -t -i:8003) 2>/dev/null
kill $(lsof -t -i:8004) 2>/dev/null

# 1. Cài dependencies
uv sync

# 2. Môi trường
cp .env.example .env        # điền API keys (máy bạn đã có .env sẵn)
set -a && source .env && set +a

# 3. Postgres (identity/booking/conversation/checkpointer)
docker compose -f configs/docker-compose.dev.yml up -d postgres

# 4. Tạo Qdrant collections (idempotent, chạy lại thoải mái) — one-time
uv run python scripts/create_collections.py

# 5. Index knowledge base vào Qdrant — one-time
uv run python -m services.rag.ingestion.run

# 6. Chạy 5 services (mỗi lệnh 1 terminal)
uv run uvicorn services.agent.main:app        --port 8000
uv run uvicorn services.identity.app:app      --port 8001
uv run uvicorn services.rag.main:app          --port 8002
uv run uvicorn services.booking.main:app      --port 8003
uv run uvicorn services.conversation.main:app --port 8004

# 7. Chat
uv run python cli.py        # /help để xem lệnh

"""
