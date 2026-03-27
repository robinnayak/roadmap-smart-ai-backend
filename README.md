# Roadmap Smart Planner Backend

## Overview

This repository contains the Django and Django REST Framework backend for DayOneGoal / Roadmap Smart Planner. It powers authentication, goal planning, AI-assisted goal generation, routines, journals, Journey Book generation, events, community read models, and the Goal Intelligence Engine (GIE).

## Tech Stack

- Python 3.12
- Django 6.0
- Django REST Framework 3.16.1
- Simple JWT
- PostgreSQL or SQLite, depending on environment configuration
- Docker and Docker Compose

## Project Layout

- Entry point: `roadmap/manage.py`
- Django settings: `roadmap/roadmap/settings.py`
- Environment template: `roadmap/.env.example`
- Docker assets:
  - `Dockerfile`
  - `docker-compose.yml`
  - `start_backend.sh`
  - `start_backend.ps1`
- Deployment assets:
  - `render.yaml`
  - `.github/workflows/django-ci.yml`

## Installed Apps

Verified Django business apps in `INSTALLED_APPS`:

- `authentication`
- `goal`
- `ai`
- `routine`
- `base`
- `journeybook`
- `journal`
- `community`
- `events`
- `gie`

## Key Features

- `Authentication` - email-first JWT authentication with register, login, logout, password reset/change, deactivate/reactivate, profile, personal details, and notification settings APIs.
- `Goal Management` - goal CRUD, create-with-hierarchy flows, financial goal feasibility, commitment contracts, timeline insight, and hierarchy progress rollups.
- `AI Processing Jobs` - current-situation analysis, goal-attribute extraction, milestone/subgoal/task hierarchy generation, and AI job-status polling.
- `Goal Intelligence Engine (GIE)` - slot-driven guided intake sessions, turn-by-turn Q&A, autofill payload generation, finalize bridge into goal creation, and adaptation proposals.
- `Routine Engine` - daily routine generation, manual task management, habit tracking, health profiles, progress dashboards, streaks, adaptive load scaling, wake-baseline support, and Daily Brief generation.
- `Journal` - per-day journal entries, search, stats, word cloud aggregation, auto-phrase polish, and summary refinement.
- `Journey Book` - eligibility checks, synchronous book generation, chapter and PDF export, demo preview/demo PDF, and derived milestone persistence.
- `Events` - calendar event CRUD, recurring and multi-day event support, range expansion, overlap metadata, and routine-constraint payloads.
- `Community` - overview feed, trending topics, community events, leaderboard snapshots, search/filtering, and discussion likes.
- `Base Platform` - root API payload, health endpoint, shared response contract, JSON renderer, and common middleware hooks.

## Architecture Overview

| Django App | Responsibility |
|---|---|
| `authentication` | Email-first user identity, JWT session lifecycle, profile settings, personal details, and notification preferences. |
| `goal` | Goal CRUD, hierarchy persistence, financial planning, commitment contracts, and timeline insight generation. |
| `ai` | AI job execution, current-situation analysis, goal-attribute extraction, hierarchy generation, and AI job-status polling. |
| `routine` | Daily routine orchestration, habits, health profiles, progress dashboards, streaks, adaptive routines, and Daily Brief. |
| `base` | Root API surface, health endpoint, and lightweight platform readiness responses. |
| `journeybook` | Journey Book generation, preview/export flows, chapter persistence, PDF output, and derived milestone data. |
| `journal` | Structured daily journaling, enrichment, search, stats, word cloud caching, and refinement helpers. |
| `community` | Read-only community overview data, trending topics, event highlights, leaderboard data, and discussion likes. |
| `events` | User-owned calendar events, recurring occurrence expansion, overlap metadata, and routine scheduling constraints. |
| `gie` | Guided goal-intake sessions, slot state, plan snapshots, finalize bridge, and adaptation proposal generation. |

## Prerequisites

- Python 3.12
- `pip`
- PostgreSQL if you want production-like local development
- Redis if you disable eager task execution

## Environment Variables

### Django Core

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `DEBUG` | Yes | Enables Django debug behavior and the browsable API renderer in development. | `False` |
| `DJANGO_ENV` | No | Environment label used by logging and deployment behavior. | `production` |
| `DJANGO_SECRET_KEY` | Yes | Django secret key for signing sessions, tokens, and cryptographic values. | `replace-production-secret` |
| `ALLOWED_HOSTS` | Yes | Comma-separated hostnames the backend will serve. | `localhost,127.0.0.1,api.example.com` |
| `CORS_ALLOWED_ORIGINS` | Yes | Comma-separated frontend origins allowed to call the API. | `http://localhost:3000,https://app.example.com` |
| `ACCESS_TOKEN_LIFETIME_MINUTES` | No | JWT access token lifetime in minutes. | `60` |
| `REFRESH_TOKEN_LIFETIME_DAYS` | No | JWT refresh token lifetime in days. | `7` |
| `MAX_ACTIVE_DEVICE_SESSIONS` | No | Maximum refresh-token sessions kept active per user; `0` disables the cap. | `0` |
| `GIE_ROLLOUT_ENABLED` | No | Enables or disables all public GIE endpoints. | `True` |
| `GIE_DEGRADED_MODE` | No | Forces GIE to return rollout-policy degraded responses. | `False` |
| `AI_DEBUG` | No | Enables extra AI/provider debug logging. | `false` |
| `SENTRY_DSN` | No | Sentry DSN for production error monitoring. | empty |
| `DISABLE_SENTRY` | No | Disables Sentry even if `SENTRY_DSN` is set. | `false` |
| `SENTRY_TRACES_SAMPLE_RATE` | No | Sentry traces sampling rate. | `0` |
| `SENTRY_PROFILES_SAMPLE_RATE` | No | Sentry profiles sampling rate. | `0` |
| `SENTRY_SEND_DEFAULT_PII` | No | Sends default user context to Sentry when enabled. | `False` |

### Database

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `DB_ENGINE` | No | Database engine. Leave empty to fall back to SQLite; set PostgreSQL in staging/production. | `django.db.backends.postgresql` |
| `DB_NAME` | Conditionally | Database name when `DB_ENGINE` is set. | `roadmap` |
| `DB_USER` | Conditionally | Database username when `DB_ENGINE` is set. | `roadmap` |
| `DB_PASSWORD` | Conditionally | Database password when `DB_ENGINE` is set. | `replace-with-db-password` |
| `DB_HOST` | Conditionally | Database host when `DB_ENGINE` is set. | `postgres` |
| `DB_PORT` | Conditionally | Database port when `DB_ENGINE` is set. | `5432` |
| `DB_CONN_MAX_AGE` | No | Persistent DB connection lifetime in seconds. | `60` |
| `DB_CONN_HEALTH_CHECKS` | No | Enables Django DB connection health checks. | `True` |
| `DB_SSLMODE` | No | PostgreSQL SSL mode for network databases. | `require` |

### AI & LLM

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `LLM_PRIMARY_PROVIDER` | No | Primary provider router used by `roadmap/ai/config.py`. | `groq` |
| `LLM_FALLBACKS` | No | Ordered provider/model fallbacks in `provider:model` format. | `openrouter:LLAMA_3_3_70B,ollama:GPT_OSS_120B` |
| `HIERARCHY_MODEL` | No | Task-specific model key for goal hierarchy generation. | `GPT_OSS_120B` |
| `JOURNEYBOOK_MODEL` | No | Task-specific model key for Journey Book generation. | `GPT_OSS_120B` |
| `TIMELINE_MODEL` | No | Task-specific model key for timeline insight generation. | `GPT_OSS_120B` |
| `CURRENT_SITUATION_MODEL` | No | Task-specific model key for current-situation analysis. | `GPT_OSS_120B` |
| `GIE_LANGUAGE_MODEL` | No | Task-specific model key for GIE language refinement. | `GPT_OSS_120B` |
| `JOURNAL_MODEL` | No | Task-specific model key for journal AI helpers. | `GPT_OSS_120B` |
| `HABIT_RECOMMENDATION_MODEL` | No | Task-specific model key for habit recommendation generation. | `GPT_OSS_120B` |
| `GOAL_ATTRIBUTE_MODEL` | No | Task-specific model key for goal-attribute extraction. | `GPT_OSS_120B` |
| `GOAL_CATEGORY_MODEL` | No | Task-specific model key for goal category resolution. | `GPT_OSS_120B` |
| `GROQ_API_KEY` | Conditionally | Groq API key when Groq is used as a primary or fallback provider. | `your-groq-key` |
| `GROQ_BASE_URL` | No | Base URL for Groq-compatible API calls. | `https://api.groq.com/openai/v1` |
| `GROQ_MODEL` | No | Default Groq model key. | `LLAMA_3_3_70B` |
| `OPENROUTER_API_KEY` | Conditionally | OpenRouter API key when OpenRouter is used as a provider or fallback. | `your-openrouter-key` |
| `OPENROUTER_BASE_URL` | No | Base URL for OpenRouter API calls. | `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL` | No | Default OpenRouter model key. | `LLAMA_3_3_70B` |
| `OPENROUTER_APP_NAME` | No | App name sent to OpenRouter. | `Roadmap Smart Planner` |
| `OPENROUTER_SITE_URL` | No | Site URL sent to OpenRouter for attribution. | `https://your-frontend-domain.com` |
| `OLLAMA_HOST` | Conditionally | Ollama host URL for local or fallback provider calls. | `http://localhost:11434` |
| `OLLAMA_MODEL` | No | Default Ollama model key. | `GPT_OSS_120B` |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | No | Request timeout for Ollama calls. | `180` |
| `OLLAMA_MAX_RETRIES` | No | Retry count for Ollama requests. | `2` |
| `OLLAMA_RETRY_BACKOFF_SECONDS` | No | Backoff interval between Ollama retries. | `0.75` |
| `OLLAMA_TRUST_ENV` | No | Allows the Ollama HTTP client to inherit proxy environment variables. | `false` |
| `HIERARCHY_MAX_MONTHS` | No | Upper bound for generated goal hierarchy duration. | `12` |
| `HIERARCHY_MAX_SUBGOALS_PER_MILESTONE` | No | Upper bound for subgoals per milestone. | `3` |
| `HIERARCHY_MAX_TASKS_PER_SUBGOAL` | No | Upper bound for tasks per subgoal. | `5` |
| `HIERARCHY_MAX_TOKENS` | No | Token budget used by hierarchy generation. | `2400` |
| `HIERARCHY_TASK_WORKERS` | No | Parallel task-generation worker count. | `2` |

### Authentication

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `EMAIL_BACKEND` | No | Django email backend used for password reset delivery. | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | Conditionally | SMTP host for password reset email. | `smtp.example.com` |
| `EMAIL_PORT` | Conditionally | SMTP port for password reset email. | `587` |
| `EMAIL_USE_TLS` | No | Enables TLS for SMTP. | `True` |
| `EMAIL_HOST_USER` | Conditionally | SMTP username. | `your-smtp-username` |
| `EMAIL_HOST_PASSWORD` | Conditionally | SMTP password. | `replace-with-your-smtp-password` |
| `DEFAULT_FROM_EMAIL` | Conditionally | Default sender address for Django email. | `noreply@example.com` |
| `PASSWORD_RESET_URL` | Conditionally | Frontend password-reset route used in reset emails; required when `DEBUG=False`. | `https://app.example.com/reset-password` |

### External Services

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `RESEND_API_KEY` | Conditionally | Resend API key for commitment-contract delivery; required when `DEBUG=False`. | `replace-with-your-resend-api-key` |
| `RESEND_FROM_EMAIL` | Conditionally | Sender address for Resend commitment-contract emails; required when `DEBUG=False`. | `Roadmap Planner <onboarding@example.com>` |
| `REDIS_URL` | Conditionally | Redis broker/result backend URL used when Celery eager mode is disabled. | `redis://localhost:6379/0` |
| `CELERY_TASK_ALWAYS_EAGER` | No | Runs tasks inline instead of through Redis-backed workers. | `False` |
| `CELERY_TASK_EAGER_PROPAGATES` | No | Propagates task exceptions immediately in eager mode. | `False` |

### Deployment

| Variable | Required | Description | Example / Default |
|---|---|---|---|
| `USE_R2_STORAGE` | No | Switches media storage from local filesystem to Cloudflare R2. | `False` |
| `R2_ENDPOINT_URL` | Conditionally | R2/S3-compatible endpoint URL when `USE_R2_STORAGE=True`. | `https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | Conditionally | Bucket name for uploaded media and PDFs. | `your-bucket-name` |
| `R2_ACCESS_KEY_ID` | Conditionally | R2 access key ID. | `replace-with-your-r2-access-key-id` |
| `R2_SECRET_ACCESS_KEY` | Conditionally | R2 secret access key. | `replace-with-your-r2-secret-access-key` |
| `R2_PUBLIC_BASE_URL` | Conditionally | Public base URL used to construct media URLs from R2. | `https://pub-YOUR_HASH.r2.dev` |

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp roadmap/.env.example roadmap/.env
python roadmap/manage.py migrate
python roadmap/manage.py runserver
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item roadmap\.env.example roadmap\.env
python roadmap\manage.py migrate
python roadmap\manage.py runserver
```

## Local vs Production Configuration

| Setting | Local Development | Production |
|---|---|---|
| `DEBUG` | Usually `True` during manual local runs; Docker compose sets `DEBUG="true"`. | `False`. Production-only validation in settings requires critical env vars to be present. |
| API host/CORS | `ALLOWED_HOSTS=localhost,127.0.0.1`; `CORS_ALLOWED_ORIGINS` points at local frontend URLs. | Restrict to deployed API domains and frontend origins only. |
| Database | SQLite when `DB_ENGINE` is empty, or local PostgreSQL through Docker Compose. | PostgreSQL via `DB_ENGINE=django.db.backends.postgresql` plus `DB_*` credentials. |
| LLM provider | Typically `ollama` for local development, with `OLLAMA_HOST` on localhost. | `groq` is the documented primary provider, with optional `openrouter` and `ollama` fallbacks. |
| Static files | WhiteNoise serves collected static files; local media can stay on filesystem. | WhiteNoise serves static assets; media should use R2 when `USE_R2_STORAGE=True`. |
| Docker usage | `docker-compose.yml` runs `web` plus `postgres` for a production-like local stack. | Build the image and inject production env vars from your host or deployment platform. |
| Background work | Eager execution is acceptable with `CELERY_TASK_ALWAYS_EAGER=True`. | Use `REDIS_URL` and disable eager mode for worker-backed execution. |

## Docker Setup

### What the checked-in files do

- `Dockerfile`
  - Base image: `python:3.12-slim`
  - Installs `build-essential` and `libpq-dev`
  - Copies `requirements.txt`, `journey_book/`, `roadmap/`, and start scripts
  - Exposes `8000`
  - Starts Gunicorn on `0.0.0.0:8000`
- `docker-compose.yml`
  - Services:
    - `web` - Django app + Gunicorn
    - `postgres` - `postgres:16-alpine`
  - Ports:
    - `8000:8000` for `web`
    - `5432:5432` for `postgres`
  - Volumes:
    - `.:/app` mounted into `web`
    - `postgres_data:/var/lib/postgresql/data` for the database
  - Env file:
    - `roadmap/.env`

### Commands

Build the images:

```bash
docker compose build
```

Start the stack:

```bash
docker compose up
```

Start in detached mode:

```bash
docker compose up -d
```

Stop and remove containers:

```bash
docker compose down
```

Run migrations inside the app container:

```bash
docker compose run --rm web python roadmap/manage.py migrate
```

Open a Django shell inside the container:

```bash
docker compose run --rm web python roadmap/manage.py shell
```

## CI/CD Pipeline

- Workflow file: `.github/workflows/django-ci.yml`
- Trigger:
  - any `push`
  - any `pull_request`
- Job:
  - `django`
- Pipeline steps:
  - checkout repository
  - set up Python 3.12 with pip cache
  - install dependencies from `requirements.txt`
  - run `python roadmap/manage.py check`
  - run `python roadmap/manage.py migrate --noinput`
  - run `python roadmap/manage.py test`
- GitHub secrets required by the current workflow:
  - none; the workflow defines CI-safe env vars inline and uses SQLite (`CI_USE_SQLITE=true`)

## API Overview

| Endpoint Group | Base Path | Description |
|---|---|---|
| Base | `/` and `/health` | Welcome payload and lightweight health checks. |
| Authentication | `/auth/` | Registration, login, logout, token refresh, password flows, profile, personal details, and notification settings. |
| Goals | `/goal/` | Goal CRUD, hierarchy creation, commitment contracts, current situation, financial profile/progress, and timeline insight. |
| Routine | `/routines/` | Daily routine generation, task lifecycle, habits, health profiles, progress dashboards, streaks, and Daily Brief. |
| Journal | `/journal/` | Journal entries, auto-phrase, summary refinement, search, stats, dates, and word cloud APIs. |
| Events | `/events/` | Event CRUD plus recurring-range expansion and overlap metadata. |
| Goal Intelligence Engine | `/gie/` | Guided intake sessions, turn processing, autofill, finalize bridge, plan retrieval, and adaptation proposals. |
| AI Utilities | `/ai/` | AI health check, current-situation processing, goal-attribute extraction, milestone generation, and job-status polling. |
| Community | `/community/` | Community overview feed and discussion-like interactions. |
| Journey Book | `/api/journeybook/` | Journey Book CRUD, eligibility, export, download, preview, and generation flows. |
| Journey Book Demo | `/journey-books/` | Public demo preview JSON and PDF endpoints. |

## Common Issues & Troubleshooting

**Problem:** Journey Book generation can still fail after the record is created.  
**Cause:** The real generation path is synchronous and can fail on AI, PDF, or storage work during `POST /api/journeybook/`.  
**Fix:** Check the saved book status first, then retry with the export/preview flows after inspecting logs: `python roadmap/manage.py test journeybook`.

**Problem:** Current-situation analysis fails because the AI provider is unavailable.  
**Cause:** Ollama/Groq/OpenRouter configuration is missing or unreachable for the selected provider route.  
**Fix:** Verify the active AI env vars and provider health, for example set `LLM_PRIMARY_PROVIDER=ollama` with `OLLAMA_HOST=http://localhost:11434`, then run `python roadmap/manage.py check`.

**Problem:** Repeated AI current-situation analysis appears stale.  
**Cause:** The feature historically froze the stored result; the fix tracker calls out refresh behavior as a required regression area.  
**Fix:** Re-run the API after updating personal details and validate with tests: `python roadmap/manage.py test ai goal`.

**Problem:** Manual routine tasks do not fit around schedule constraints as expected.  
**Cause:** The issue registry calls out schedule-fit enforcement for manual task create/update paths as a routine risk area.  
**Fix:** Regenerate the routine after changing events or task load: `POST /routines/generate/` with `force=true`, or rerun regression coverage with `python roadmap/manage.py test routine events`.

**Problem:** Daily Brief does not reflect recurring or multi-day events correctly.  
**Cause:** The routine issue tracker documents event-loading gaps on the brief path versus the full event-expansion path.  
**Fix:** Validate event expansion through `/events/range/`, then rerun routine/event regression tests: `python roadmap/manage.py test routine events`.

**Problem:** Password reset appears to succeed but no email arrives.  
**Cause:** `PASSWORD_RESET_URL` or SMTP configuration is missing; the forgot-password flow depends on those settings.  
**Fix:** Set `PASSWORD_RESET_URL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD` in `roadmap/.env`, then test with `python roadmap/manage.py test authentication`.

## References

- Backend environment template: `roadmap/.env.example`
- Backend settings: `roadmap/roadmap/settings.py`
- Feature map summary: `../project_docs/backend-feature-map/00_SUMMARY.md`
- Environment guide: `../project_docs/apis/production/ENVIRONMENT_AND_SERVICE_SWITCHING_GUIDE_BACKEND.md`
- Backend production audit: `../project_docs/apis/production/backend_production_audit.md`
