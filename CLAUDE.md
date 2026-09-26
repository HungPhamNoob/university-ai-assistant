# CLAUDE.md — UET AI Assistant

Repository guidance for every coding agent. Read hint.md and the applicable
.claude/rules files before changing code. For implementation work, also follow
.claude/skills/coding-simple/SKILL.md. For visible frontend work, follow
.claude/skills/frontend-design/SKILL.md.

## Product truth

This repository is UET-only. Do not introduce names, examples, identifiers,
collection names, environment variables, UI copy or test fixtures from another
organization.

The current knowledge source is data/UET_HR.pdf. It is a generated reference
draft dated 26-09-2026, not an official regulation or live facility directory.
The room/class registry is explicitly illustrative. State that limitation in
answers where it matters; never invent missing street addresses, contacts,
opening hours, fees or official status.

## Engineering rules

- Keep code direct, typed and readable. Prefer a small clear function over a
  new abstraction without demonstrated reuse.
- Preserve service boundaries. New runtime code belongs in services/name, not
  src/.
- Agent prompts belong in services/agent/prompts/ and are loaded by its
  loader.py. Never duplicate prompt bodies in Python.
- Prompt edits must specify concrete required fields per entity, CONTINUE
  rules, STOP rules, failure disclosure and a hard tool-call limit.
- Primary router returns only an intent decision. The selected subagent owns
  the answer.
- Tool loops stop only when required fields have evidence or the explicit
  exhaustion/error rules apply. Never infer a missing fact.
- Booking write operations always require HITL approval. Read-only room
  discovery does not.
- Do not weaken gateway, internal-token, ownership, JWT or sanitization checks
  to make a test pass.
- Business-table schema changes require an Alembic revision in the owning
  service. Do not use create_all as a migration substitute.
- Qdrant Cloud is the only vector store path; Redis Cloud is the only Redis
  path. No local Qdrant or Redis container.
- Episodic memory is SQL-only, isolated by user and thread, and injected as
  untrusted data.
- Never print or commit secrets. Preserve unrelated user changes.

## System layout

~~~text
services/agent/         LangGraph, context assembly, tools and prompts
services/identity/      Users, password hashing and JWT
services/rag/           PDF ingestion and retrieval
services/booking/       Room catalog, availability and booking CRUD
services/conversation/  Messages, Redis response cache and episodic summaries
services/gateway/       Kong DB-less config
services/frontend/      Static browser UI
eval/                   Maintained smoke, graph, UI and RAGAS evaluation
tests/                  Pytest suite
scripts/local.sh        Full local lifecycle
~~~

Authoritative default names:

- database: uet_ai_db
- knowledge collection: uet_hr_docs
- semantic cache collection: uet_hr_cache
- source PDF: data/UET_HR.pdf
- prompt package: services.agent.prompts

## Required workflow

1. Inspect existing code, hint.md and current data before editing.
2. Make the smallest coherent cross-service change.
3. Run formatting and static checks.
4. Run focused tests, then the full pytest suite.
5. Start the full stack with bash scripts/local.sh.
6. Exercise service smoke tests, LangGraph flows, real Redis/Qdrant behavior,
   browser UI and RAGAS with live contexts.
7. Read logs and fix root causes; repeat dependent checks.
8. Audit tracked files, ignored artifacts, forbidden old-domain terms and
   staged secrets.
9. Use Conventional Commits. Publish only after validation.
10. Stop the full stack with bash scripts/local.sh down.

Core commands:

~~~bash
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest -q
bash scripts/local.sh
uv run python eval/service_smoke_test.py
uv run python eval/flow_test.py
UI_E2E_LIMIT_PER_SECTION=1 uv run python eval/ui_e2e_playwright.py
RAGAS_LIMIT=6 uv run python eval/evaluate_ragas.py
bash scripts/local.sh down
~~~

## Configuration

All local values come from .env, copied from .env.example. Important groups:

- LLM: LLM_MODEL, API_KEY, BASE_URL and optional backup provider settings.
- Retrieval: QDRANT_URL, QDRANT_API_KEY, QDRANT_KB_COLLECTION,
  QDRANT_CACHE_COLLECTION, embedding/reranker and HyDE settings.
- Search: TAVILY_API_KEY.
- Database: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD,
  POSTGRES_DB.
- Cache: REDIS_ENABLED and REDIS_URL.
- Auth: JWT_SECRET_KEY, JWT_ISSUER, GATEWAY_SHARED_SECRET,
  INTERNAL_API_TOKEN and AGENT_REQUIRE_GATEWAY.
- Context: TOKEN_BUDGET_* and episodic settings.

Gateway configuration keeps placeholders in source. The entrypoint renders
secrets and upstream hosts at runtime.

## Review checklist

- Does every answerable claim come from tool evidence or stable system input?
- Does each tool-using prompt enumerate fields for person, room/facility,
  service, policy, academic program, lab/project, event and comparison cases?
- Can every loop terminate on success, absence, repeated error and hard limit?
- Are non-ACTIVE rooms impossible to book?
- Are writes behind explicit approval?
- Are user/thread boundaries maintained in database, cache and memory?
- Are UET caveats shown without making the assistant unusably repetitive?
- Does the staged tree exclude .env, logs, tmp, reference, problems, src,
  generated eval output, state, bytecode and obsolete images?
- Did all required checks run against the same commit candidate?
