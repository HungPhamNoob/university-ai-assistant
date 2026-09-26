#!/usr/bin/env python
# ============================================
# eval/ui_e2e_playwright.py
# ============================================
"""E2E test: chạy queries.txt qua Web UI thật (Playwright Chromium).

Mục đích: xác nhận auth, UI, SSE, agent/tool status và HITL qua frontend thật.

Hành vi:
- Đăng ký một user test mới (không đụng dữ liệu user thật).
- Mỗi query chạy trong một NEW CHAT riêng (thread sạch, không nhiễu context).
- HITL (booking approval) luôn bị REJECT ("Hủy") -> không ghi booking thật.
- Ghi nhận: trạng thái turn (done/error/timeout), agent, số tool, thời gian,
  console error, network failure, answer preview; chụp screenshot khi lỗi.

Usage:
    UI_E2E_LIMIT_PER_SECTION=1 uv run python eval/ui_e2e_playwright.py [BASE_URL]

Kết quả: /tmp/ui_e2e_results.json + /tmp/ui_e2e_results.md + /tmp/ui_e2e_shots/
"""

import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000/"
ROOT = Path(__file__).resolve().parent.parent
QUERIES_FILE = ROOT / "eval" / "queries.txt"
SHOTS_DIR = Path("/tmp/ui_e2e_shots")

PER_QUERY_TIMEOUT_S = 240
POLL_MS = 500

# Reads the UI state of the LAST turn in the chat log. Pure DOM read — mirrors
# exactly what a human sees: error card, HITL card, or completed timeline.
JS_TURN_STATE = """
() => {
  const turns = document.querySelectorAll('#chat-log section.turn');
  if (!turns.length) return {state: 'no-turn'};
  const t = turns[turns.length - 1];
  const err = t.querySelector('.error-card');
  if (err) {
    const msg = err.querySelector('.error-message');
    return {state: 'error', message: (msg ? msg.textContent : err.textContent).trim()};
  }
  // An unresolved HITL card still has its reject button in the DOM; after
  // Đồng ý/Hủy the buttons are replaced by a .hitl-resolved span.
  if (t.querySelector('.hitl-card .btn-reject')) return {state: 'hitl'};
  if (t.querySelector('.timeline.is-done')) {
    const label = t.querySelector('.ts-label');
    const meta = t.querySelector('.ts-meta');
    const answer = t.querySelector('.answer-body');
    return {
      state: 'done',
      agent: label ? label.textContent.trim() : '',
      meta: meta ? meta.textContent.trim() : '',
      answer: answer ? answer.textContent.trim().slice(0, 200) : '',
    };
  }
  return {state: 'streaming'};
}
"""


def load_queries() -> list[str]:
    queries = []
    current_section = "unclassified"
    per_section = int(os.getenv("UI_E2E_LIMIT_PER_SECTION", "0"))
    section_counts: dict[str, int] = {}
    for line in QUERIES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_section = line.lstrip("# ").strip() or "unclassified"
            continue
        if per_section > 0 and section_counts.get(current_section, 0) >= per_section:
            continue
        queries.append(line)
        section_counts[current_section] = section_counts.get(current_section, 0) + 1
    limit = int(os.getenv("UI_E2E_LIMIT", "0"))
    return queries[:limit] if limit > 0 else queries


def register_user(page) -> str:
    email = f"e2e.sse.{int(time.time())}@example.com"
    page.click("#auth-tab-register")
    page.fill("#auth-name", "E2E SSE Tester")
    page.fill("#auth-email", email)
    page.fill("#auth-password", "Test@123456")
    page.click("#auth-submit")
    page.wait_for_selector("#chat-input", state="visible", timeout=30_000)
    return email


def run_query(page, query: str) -> dict:
    """Send one query in a fresh chat and watch the turn until terminal state."""
    page.click("#new-chat-btn")
    page.wait_for_timeout(400)
    page.fill("#chat-input", query)
    page.click("#send-btn")

    start = time.time()
    state = {"state": "streaming"}
    hitl_rejects = 0
    while time.time() - start < PER_QUERY_TIMEOUT_S:
        state = page.evaluate(JS_TURN_STATE)
        if state["state"] == "hitl" and hitl_rejects < 3:
            # REJECT every approval: this suite tests stream health, and must
            # never write real bookings into the production database.
            page.click("#chat-log section.turn:last-of-type .btn-reject")
            hitl_rejects += 1
            page.wait_for_timeout(600)
            continue
        if state["state"] in ("done", "error", "no-turn"):
            break
        page.wait_for_timeout(POLL_MS)
    else:
        state = {"state": "timeout"}

    return {
        "status": state["state"],
        "elapsed_s": round(time.time() - start, 1),
        "agent": state.get("agent", ""),
        "meta": state.get("meta", ""),
        "answer_preview": state.get("answer", ""),
        "ui_error": state.get("message", ""),
        "hitl_rejects": hitl_rejects,
    }


def main() -> int:
    SHOTS_DIR.mkdir(exist_ok=True)
    queries = load_queries()
    results = []
    console_errors: list[str] = []
    net_failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on(
            "requestfailed",
            lambda r: net_failures.append(f"{r.url} :: {r.failure}"),
        )

        print(f"==> Opening {BASE}", flush=True)
        page.goto(BASE, wait_until="domcontentloaded", timeout=60_000)
        # #chat-input tồn tại trong DOM nhưng bị ẨN khi chưa đăng nhập (nó nằm
        # trong #app-view.hidden) — phải chờ đúng phần tử visible của màn auth.
        page.wait_for_selector("#auth-email", state="visible", timeout=30_000)

        email = register_user(page)
        print(f"==> Registered test user {email}", flush=True)

        for i, query in enumerate(queries, 1):
            console_errors.clear()
            net_failures.clear()
            row = {"i": i, "query": query}
            row.update(run_query(page, query))
            row["console_errors"] = list(console_errors)[:5]
            row["net_failures"] = list(net_failures)[:5]
            results.append(row)

            flag = "OK " if row["status"] == "done" else "FAIL"
            print(
                f"[{i:2d}/{len(queries)}] {flag} {row['status']:9s} "
                f"{row['elapsed_s']:6.1f}s  hitl={row['hitl_rejects']}  {query[:58]}",
                flush=True,
            )
            if row["status"] != "done":
                page.screenshot(path=str(SHOTS_DIR / f"q{i:02d}-{row['status']}.png"))

        browser.close()

    # ---- summary ----
    out_json = Path("/tmp/ui_e2e_results.json")
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    ok = sum(1 for r in results if r["status"] == "done")
    lines = [
        "# UI E2E results — " + time.strftime("%Y-%m-%d %H:%M"),
        "",
        f"Base: {BASE}",
        f"Pass: **{ok}/{len(results)}**",
        "",
        "| # | Query | Status | Agent | Elapsed | HITL reject | Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        err = r["ui_error"] or "; ".join(r["console_errors"] + r["net_failures"])[:80]
        lines.append(
            f"| {r['i']} | {r['query'][:50]} | {r['status']} | {r['agent']} "
            f"| {r['elapsed_s']}s | {r['hitl_rejects']} | {err[:80]} |"
        )
    Path("/tmp/ui_e2e_results.md").write_text("\n".join(lines))
    print(f"\n==> SUMMARY: {ok}/{len(results)} passed. Details: {out_json}", flush=True)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
