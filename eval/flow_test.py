# ============================================
# eval/flow_test.py
# ============================================
"""
End-to-end routing/flow test against the running Agent service (port 8000).

- Reads queries from eval/queries.txt (section headers define the expected flow).
- Skips ticket-related queries (per user instruction).
- Booking-room queries are APPROVED automatically to exercise the HITL path.
- Detects the ACTUAL flow with GROUND TRUTH from the Postgres checkpointer:
  the parent-graph checkpoint `writes` show which node ran
  (router -> faq_node / search_node / booking_node / chat_node).
  SSE tool/interrupt events are kept as secondary evidence.
- Writes a markdown report to eval/flow_test_results.md
"""

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from psycopg import connect

from services.agent.config import settings

CONNINFO = settings.POSTGRES_URI.replace("+psycopg", "")
NODE_TO_FLOW = {
    "chat_node": "general_chat",
    "faq_node": "faq_agent",
    "search_node": "search_agent",
    "booking_node": "booking_agent",
}

# Direct agent URL (KHÔNG dùng AGENT_SERVICE_URL — biến đó dành cho cli.py và
# có thể trỏ Kong gateway, nơi không có route cho flow test không-JWT).
BASE = os.getenv("FLOW_AGENT_URL", "http://localhost:8000") + "/api/chat"
# Giả lập header do Kong inject: cần khi AGENT_REQUIRE_GATEWAY=true, bị bỏ
# qua khi false — flow test chạy được ở cả 2 chế độ. X-User-Id khớp user_id
# trong body ("flow-test") nên chủ sở hữu booking HITL không đổi.
FLOW_HEADERS = {
    "X-Gateway-Token": settings.GATEWAY_SHARED_SECRET,
    "X-User-Id": "flow-test",
}
QUERIES_FILE = "eval/queries.txt"
OUT_FILE = "eval/flow_test_results.md"
TIMEOUT = 300.0

# section marker -> label
SECTION_MAP = [
    ("GENERAL", "general_chat"),
    ("UET KNOWLEDGE", "faq_agent"),
    ("WEB SEARCH", "search_agent"),
    (
        "BOOKING",
        "ticket_section",
    ),  # booking queries with HITL (label kept to reuse existing logic)
]

# Queries where more than one routing is defensible.
ACCEPT_OVERRIDES = {
    # Static world knowledge can be answered from memory or live search.
    "Ai là người sáng lập ra Microsoft?": {"general_chat", "search_agent"},
    # Room-status lookup: primary.md routes operational "status" to booking_agent
    # (live catalog), but it is also answerable from the PDF registry via faq_agent.
    "Những phòng nào đang ở trạng thái MAINTENANCE hoặc RESTRICTED?": {
        "booking_agent",
        "faq_agent",
    },
    # Context-dependent: "never mind booking + thanks" is a booking follow-up in a
    # live conversation, but reads as small talk on an isolated (fresh) thread.
    "Thôi không cần đặt phòng nữa, cảm ơn bạn.": {"booking_agent", "general_chat"},
}


def parse_queries(path: str):
    """Return list of (query, expected_flow, section_label)."""
    items = []
    current = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                upper = line.upper()
                for marker, label in SECTION_MAP:
                    if marker in upper:
                        current = label
                        break
                continue
            if current is None:
                continue
            if current == "ticket_section":
                if re.search(r"ticket", line, re.IGNORECASE):
                    print(f"[skip ticket] {line}")
                    continue
                items.append((line, "booking_agent", "BOOKING (HITL)"))
            else:
                items.append((line, current, current))
    return items


def limit_per_section(items):
    """Optionally keep a balanced number of queries from every section."""
    limit = int(os.getenv("FLOW_LIMIT_PER_SECTION", "0"))
    if limit <= 0:
        return items

    selected = []
    counts = {}
    for item in items:
        section = item[2]
        if counts.get(section, 0) >= limit:
            continue
        selected.append(item)
        counts[section] = counts.get(section, 0) + 1
    return selected


def detect_flow(tools, interrupt, nodes=None):
    """Ground truth from parent-graph checkpoint nodes; SSE as fallback."""
    for node in nodes or []:
        if node in NODE_TO_FLOW:
            return NODE_TO_FLOW[node]
    if interrupt and interrupt.get("action") in (
        "book_room",
        "cancel_booking",
        "reschedule_booking",
    ):
        return "booking_agent"
    if "search_uet_knowledge" in tools:
        return "faq_agent"
    if "search_web" in tools:
        return "search_agent"
    return "general_chat"


def get_node_seq(thread_id: str):
    """Read parent-graph checkpoints; return ordered nodes via `branch:to:*` channels."""
    nodes = ["router"]
    try:
        with connect(CONNINFO) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT checkpoint->'updated_channels' FROM checkpoints "
                "WHERE thread_id = %s ORDER BY checkpoint_id",
                (thread_id,),
            )
            for (upd,) in cur.fetchall():
                for ch in upd or []:
                    if isinstance(ch, str) and ch.startswith("branch:to:"):
                        node = ch[len("branch:to:") :]
                        if node in NODE_TO_FLOW and node not in nodes:
                            nodes.append(node)
    except Exception as e:  # noqa: BLE001  # pragma: no cover - audit helper
        nodes = [f"DB_ERROR: {e}"]
    return nodes


async def run_one(client: httpx.AsyncClient, query: str):
    """Send one query on a fresh thread; auto-approve HITL. Returns info dict."""
    thread_id = f"flowtest-{uuid.uuid4().hex[:8]}"
    info = {
        "thread_id": thread_id,
        "tools": [],
        "interrupt": None,
        "tokens": [],
        "errors": [],
        "resumed": False,
    }

    async def consume(url, payload):
        async with client.stream("POST", url, json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                ev = data.get("event")
                if ev == "token":
                    info["tokens"].append(data.get("data", ""))
                elif ev == "tool":
                    if data.get("data", {}).get("status") == "start":
                        info["tools"].append(data.get("data", {}).get("name"))
                elif ev == "interrupt":
                    info["interrupt"] = data.get("data") or {}
                elif ev == "error":
                    info["errors"].append(str(data.get("data")))

    await consume(
        f"{BASE}/stream",
        {"thread_id": thread_id, "message": query, "user_id": "flow-test"},
    )
    if info["interrupt"]:
        info["resumed"] = True
        # user_id PHẢI giống pha stream: thiếu nó, resume rơi về 'anonymous'
        # và booking sau approve bị ghi sai chủ sở hữu.
        await consume(
            f"{BASE}/resume",
            {
                "thread_id": thread_id,
                "decision": {"approved": True},
                "user_id": "flow-test",
            },
        )
    # Ground truth: which parent-graph nodes ran (from Postgres checkpointer)
    info["nodes"] = await asyncio.to_thread(get_node_seq, thread_id)
    return info


def write_report(lines: list[str]) -> None:
    """Write the plain-text report; sync so async main() performs no blocking I/O."""
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main():
    items = limit_per_section(parse_queries(QUERIES_FILE))
    print(f"Total queries to test: {len(items)}")
    rows = []
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=FLOW_HEADERS) as client:
        for i, (query, expected, section) in enumerate(items, 1):
            print(f"\n[{i}/{len(items)}] ({section}) {query}")
            try:
                info = await run_one(client, query)
            except Exception as e:  # noqa: BLE001 - network / service level failure
                info = {
                    "thread_id": "n/a",
                    "tools": [],
                    "interrupt": None,
                    "tokens": [],
                    "errors": [f"EXC: {e}"],
                    "resumed": False,
                    "nodes": [],
                }
            actual = detect_flow(info["tools"], info["interrupt"], info.get("nodes"))
            acceptable = ACCEPT_OVERRIDES.get(query, {expected})
            ok = actual in acceptable and not info["errors"]
            answer = "".join(info["tokens"]).strip()
            excerpt = re.sub(r"\s+", " ", answer)[:400]
            node_seq = " -> ".join(info.get("nodes") or []) or "-"
            print(
                f"   expected={expected} actual={actual} nodes=[{node_seq}] "
                f"tools={info['tools']} interrupt={bool(info['interrupt'])} "
                f"resumed={info['resumed']} errors={info['errors']}"
            )
            print(f"   answer: {excerpt[:200]}...")
            rows.append(
                {
                    "i": i,
                    "section": section,
                    "query": query,
                    "expected": expected,
                    "actual": actual,
                    "acceptable": "/".join(sorted(acceptable)),
                    "tools": ", ".join(info["tools"]) or "-",
                    "nodes": node_seq,
                    "hitl": ("approve" if info["resumed"] else "-"),
                    "ok": "PASS" if ok else "FAIL",
                    "errors": "; ".join(info["errors"]) or "-",
                    "excerpt": excerpt,
                }
            )

    lines = [
        "# Flow Test Results (eval/queries.txt)",
        "",
        "Ticket queries skipped. Booking queries auto-approved (HITL).",
        "Actual flow detected with GROUND TRUTH from the Postgres checkpointer:",
        "each thread's checkpoint `updated_channels` shows the branch taken",
        "(`branch:to:<node>`): `chat_node`=general, `faq_node`=RAG/FAQ,",
        "`search_node`=Tavily, `booking_node`=booking/HITL.",
        "SSE tool/interrupt events are secondary evidence.",
        "",
        "| # | Section | Query | Expected | Actual | Node sequence | Tools | HITL | Result |",
        "|---|---------|-------|----------|--------|---------------|-------|------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['i']} | {r['section']} | {r['query']} | {r['expected']} "
            f"| {r['actual']} | {r['nodes']} | {r['tools']} | {r['hitl']} "
            f"| {r['ok']} |"
        )
    lines += ["", "## Answer excerpts", ""]
    for r in rows:
        lines += [
            f"### [{r['i']}] {r['query']}",
            (
                f"- expected: `{r['expected']}` | actual: `{r['actual']}` | "
                f"result: **{r['ok']}** | errors: {r['errors']}"
            ),
            f"- nodes: `{r['nodes']}`",
            f"- answer: {r['excerpt']}",
            "",
        ]
    write_report(lines)

    n_pass = sum(1 for r in rows if r["ok"] == "PASS")
    print(f"\n==== SUMMARY: {n_pass}/{len(rows)} PASS ====")
    for r in rows:
        print(
            f"{r['ok']}  [{r['section']}] expected={r['expected']} "
            f"actual={r['actual']}  {r['query']}"
        )
    print(f"Report written to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
