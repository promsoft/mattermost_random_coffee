# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Phase 1 (MVP) complete: registration/pause/profile via DM buttons + text commands, weekly matching with 365-day pair cooldown, pair intro in group channels, channel announcements, help. Next phases (see `spec/plan.md`): status/rating cycle → decline/postpone → admin/complaints. Documents (in Russian):

- `spec/random-coffee-bot.md` — product spec + clarified decisions
- `spec/architecture.md` — stack, components, data model, matching algorithm, meeting state machine
- `spec/plan.md` — phased execution plan (each phase ends with a deployable bot)
- `spec/backlog.md` — future ideas not tied to plan phases (offline/online formats, city, timezone, etc.)
- `spec/security.md` — trust boundaries, button-callback auth scheme, secrets handling; consult before changing auth/TLS/secrets-related code

## Chosen Stack

Python 3.12+ standalone bot (not a plugin): `mattermostdriver` (REST + WebSocket), FastAPI endpoint for interactive button callbacks, APScheduler (cron jobs Mon/Wed/Sun, Europe/Moscow), SQLite + SQLAlchemy + Alembic, pydantic-settings, Docker Compose deployment on the same host as Mattermost. Tests: pytest; lint: ruff. Scale: community of 4000+, but expect tens of active participants at start; design for growth to hundreds.

## Development Environment

- Python env: pyenv virtualenv `projects_mattermost_random_coffee` (Python 3.12), auto-activated via `.python-version` — do not create another venv.
- Dependencies: declare top-level deps in `requirements.in`, compile with `uv pip compile requirements.in -o requirements.txt`, install with `uv pip install -r requirements.txt` (NOT `uv pip sync` — it would uninstall `uv`/`pip` themselves from the venv).
- The package is installed editable (`uv pip install -e .`), src-layout: code in `src/coffeebot/`.

## Commands

```bash
python -m pytest -q                  # tests (single test: python -m pytest tests/test_events.py::test_echo_on_direct_message)
ruff check .                         # lint (alembic/versions excluded)
alembic upgrade head                 # apply DB migrations (DB_PATH env or .env controls target)
alembic revision --autogenerate -m "..."   # new migration after model changes
python -m coffeebot.main             # run the bot (needs MM_URL, MM_BOT_TOKEN in .env)
docker compose up -d --build         # production-style run
```

## Architecture Notes

- Single asyncio loop in `main.py` runs three things: WebSocket listener (DM commands), uvicorn HTTP server (button callbacks at `/actions/{secret}`), APScheduler (Monday matching cron + startup catch-up).
- Layering: `events.parse_dm` (pure parsing) → `handlers.BotHandlers` (scenarios) → `services/` (domain logic, pure DB) + `mm.MattermostGateway` (all network sends). Tests use `FakeGateway` from `tests/conftest.py`. Keep domain logic free of network calls.
- All user-facing strings live in `texts.py` (Russian); buttons built in `cards.py`.
- Idempotency invariants: matching is once-per-`week_start`; pair notifications gate on `meetings.notified_at` (committed one-by-one); restart never duplicates sends.
- Button callback auth: Mattermost Free doesn't sign action POSTs — auth is the secret in the URL path (`ACTIONS_SECRET`, mandatory) + endpoint bound to internal network only.
- `mm_websocket.ClientTLSWebsocket` fixes mattermostdriver's server-side SSL context bug; always pass it to `init_websocket`/use directly.
- DB: models in `coffeebot.db.models` (StrEnum → VARCHAR, non-native); Alembic `env.py` reads the DB URL from `Settings` (`.env`/`DB_PATH`), `render_as_batch=True` for SQLite ALTERs.

## What This Project Is

A "Random Coffee" bot for a self-hosted **Mattermost server (Free Edition, version 11)** that organizes weekly random 1:1 video calls between community members.

Key requirements from the spec:

- **Participation**: users register, opt out, or pause via the bot; each user has a short profile with contact info (Telegram, WhatsApp, etc.)
- **Weekly cycle**: random pairs are formed every Monday and notified; mid-week the bot asks for status (agreed / called / cancelled / not yet in touch); end of week it asks for a 0–5 rating (0 = terrible)
- **Matching rules**:
  - Pairing prioritizes high-rating users together (rating = sum of ratings across completed meetings)
  - A pair cannot repeat within one year, regardless of whether the call happened
  - A user can decline a match and try another pair from the unmatched pool
  - A pair can propose postponing to next week; the partner either accepts or cancels (cancelled = meeting did not happen)
- **History**: all meetings are stored
- **Admin**: can cancel any meeting, view scheduled meetings / participants / ratings, and force-pause any user (no editing of meetings needed)
- **Complaints**: a participant can report their meeting partner, which pauses the reported user until an admin unblocks them
- **Help**: the bot provides concise but informative usage/how-it-works help

The spec ends with an open request: clarify details with the user, research random coffee bot best practices from other communities, and start with a minimum viable feature set.

## Conventions

- The spec and user communication are in Russian; keep user-facing bot texts in Russian unless decided otherwise.
- Target platform constraint: Mattermost **Free Edition** — features requiring paid licenses are unavailable.
