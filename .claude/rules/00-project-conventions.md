---
description: UET AI Assistant project-wide conventions
globs: ["**/*"]
alwaysApply: true
---

# Project conventions

- Runtime code lives under services/. Do not add code to src/.
- Agent prompt files live under services/agent/prompts/ and are loaded through
  services.agent.prompts.loader.
- Keep the UET domain consistent in code, identifiers, UI, tests, examples,
  infrastructure and documentation.
- data/UET_HR.pdf is a generated reference draft. Do not claim that its policy
  or illustrative room registry is official/live data.
- Qdrant collections default to uet_hr_docs and uet_hr_cache.
- Redis is managed through REDIS_URL only; do not add a Redis container.
- Every service keeps its own config and API boundary. Use HTTP clients between
  services, not cross-service database access.
- Use async FastAPI/HTTP clients and typed Pydantic models at boundaries.
- Services owning business tables own their Alembic migrations.
- All booking creates, updates/reschedules and cancellations require HITL.
- Prompts using tools must enumerate concrete output fields plus CONTINUE,
  STOP, missing-data and maximum-call rules.
- Tests use pytest and pytest-asyncio. Maintained eval entry points are
  service_smoke_test.py, flow_test.py, ui_e2e_playwright.py and
  evaluate_ragas.py.
- Change dependencies in pyproject.toml, then run uv lock.
- Never commit .env, credentials, logs, tmp, reference, problems, src,
  generated reports, Terraform state, bytecode or obsolete screenshots.
- Run the full verification gate in CLAUDE.md before publishing.
