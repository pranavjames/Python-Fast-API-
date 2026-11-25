# TaskFlow API

Production-ready REST API for managing **users** and their **tasks**, where every task has its
own timeline (optional start date + required due date). Built with **FastAPI**, **SQLAlchemy 2
(async)**, **MySQL 8** and **Alembic**.

## Features

- **JWT authentication** — OAuth2 password flow, short-lived access tokens + refresh tokens, bcrypt hashing
- **Role-based access** — `user` and `admin` roles; admins manage users and assign tasks
- **User profiles** — name, email, phone, job title; self-service profile and password updates
- **Tasks with individual deadlines** — each task has its own `due_date` (and optional `start_date`),
  with computed `is_overdue` and `days_remaining`
- **Status lifecycle** — `pending → in_progress → completed / cancelled` with validated transitions
  and automatic `completed_at` tracking
- **Timeline view** — open tasks grouped by due date, plus overdue tasks
- **Summary** — counts by status, overdue, due today, due in the next 7 days
- **Filtering, sorting, pagination** — by status, priority, due-date range, overdue flag, text search
- **Production concerns** — layered architecture, Alembic migrations, structured JSON logging with
  request IDs, consistent error envelope, health/readiness probes, security headers, CORS, GZip,
  connection pooling, config validation, multi-stage non-root Docker image, CI pipeline

## Project structure

```
.
├── app/
│   ├── main.py                  # App factory: middleware, routers, exception handlers
│   ├── api/
│   │   ├── deps.py              # DI: DB session, services, auth, pagination
│   │   └── v1/
│   │       ├── router.py        # Aggregates v1 routers
│   │       └── endpoints/       # auth, users, tasks, health
│   ├── core/
│   │   ├── config.py            # Typed settings (pydantic-settings) + production guardrails
│   │   ├── security.py          # bcrypt hashing, JWT encode/decode
│   │   ├── exceptions.py        # Domain exceptions → HTTP error envelope
│   │   └── logging.py           # JSON logging with request-id correlation
│   ├── db/
│   │   ├── base.py              # Declarative base, naming conventions, UTC datetime type, mixins
│   │   └── session.py           # Async engine, pool config, session dependency
│   ├── models/                  # SQLAlchemy ORM models (User, Task)
│   ├── schemas/                 # Pydantic request/response models
│   ├── repositories/            # Data-access layer (queries only, no commits)
│   ├── services/                # Business logic & transactions
│   ├── middleware/              # Request ID, access log, security headers, 500 handling
│   └── commands/                # CLI commands (create admin)
├── alembic/                     # Database migrations
├── tests/
│   ├── api/                     # HTTP-level tests per resource
│   └── unit/                    # Security, schemas, config, core utilities
├── scripts/start.sh             # Container entrypoint (migrate + uvicorn)
├── Dockerfile                   # Multi-stage, non-root, healthcheck
├── docker-compose.yml           # API + MySQL 8.4
├── .github/workflows/ci.yml     # Lint, type-check, tests on MySQL, Docker build
└── pyproject.toml               # Project metadata + ruff/mypy/pytest/coverage config
```

**Request flow:** `endpoint → service → repository → database`. Endpoints handle HTTP concerns only,
services own business rules and transaction boundaries (`commit`), repositories own queries (`flush`).

## Quick start

### Option A — Docker (recommended)

```bash
cp .env.example .env          # then set SECRET_KEY, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD
docker compose up --build -d
docker compose exec api python -m app.commands.create_admin --email admin@example.com
```

The API is at http://localhost:8000 — interactive docs at http://localhost:8000/docs.
Migrations run automatically on container start (`RUN_MIGRATIONS=true`).

### Option B — Local Python

Requires Python 3.11+ and a running MySQL 8 server.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # point MYSQL_* at your server
alembic upgrade head
python -m app.commands.create_admin --email admin@example.com
uvicorn app.main:app --reload
```

## API overview

All endpoints are under `/api/v1`. Authenticate with `Authorization: Bearer <access_token>`.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health/live` | – | Liveness probe |
| GET | `/health/ready` | – | Readiness probe (checks DB) |
| POST | `/auth/register` | – | Register a user |
| POST | `/auth/login` | – | Get tokens (form: `username`=email, `password`) |
| POST | `/auth/refresh` | – | Exchange refresh token for a new pair |
| GET / PATCH | `/users/me` | user | View / update own profile |
| POST | `/users/me/password` | user | Change password |
| GET / POST | `/users` | admin | List (search, role, is_active) / create users |
| GET / PATCH / DELETE | `/users/{id}` | admin | Manage a user (delete cascades to tasks) |
| GET / POST | `/users/{id}/tasks` | admin | List a user's tasks / assign a task |
| POST | `/tasks` | user | Create a task |
| GET | `/tasks` | user | List with filters, sorting, pagination |
| GET | `/tasks/timeline` | user | Open tasks grouped by due date + overdue |
| GET | `/tasks/summary` | user | Counts by status and deadline |
| GET / PATCH / DELETE | `/tasks/{id}` | user | Read / update / delete own task |
| PATCH | `/tasks/{id}/status` | user | Change status (validated transitions) |

### Task list query parameters

| Param | Example | Notes |
|---|---|---|
| `status` | `status=pending&status=in_progress` | repeatable |
| `priority` | `priority=high` | repeatable: `low`, `medium`, `high`, `urgent` |
| `due_from`, `due_to` | `due_from=2026-12-01` | inclusive date range |
| `overdue` | `overdue=true` | open tasks past their due date |
| `search` | `search=report` | title/description, case-insensitive |
| `sort_by`, `sort_order` | `sort_by=priority&sort_order=desc` | `due_date` (default), `priority`, `created_at`, `title`, `status` |
| `page`, `size` | `page=2&size=20` | `size` ≤ 100 |

### Business rules

- `due_date` is required and cannot be in the past when a task is created or its due date is changed.
- `start_date`, if given, must be on or before `due_date`.
- New tasks start as `pending` or `in_progress`.
- Allowed transitions: `pending ↔ in_progress`, either → `completed`/`cancelled`,
  `completed → pending/in_progress` (reopen), `cancelled → pending` (reopen).
- `completed_at` is set when a task is completed and cleared when it is reopened.
- A task is **overdue** when it is open (`pending`/`in_progress`) and its due date is before today (UTC).
- Admins cannot delete, deactivate or demote themselves.

### Example

```bash
# Register and log in
curl -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"jane@example.com","password":"Secret123","full_name":"Jane Doe"}'
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -d 'username=jane@example.com&password=Secret123' | jq -r .access_token)

# Create a task due on a specific date
curl -X POST localhost:8000/api/v1/tasks -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Ship v1","priority":"high","start_date":"2026-12-01","due_date":"2026-12-15"}'

# What's coming up?
curl localhost:8000/api/v1/tasks/timeline -H "Authorization: Bearer $TOKEN"
```

### Error format

Every error uses the same envelope, and every response carries an `X-Request-ID` header
(propagated from the client if supplied) that also appears in the logs:

```json
{
  "error": { "code": "business_rule_violation", "message": "due_date cannot be in the past" },
  "request_id": "29f46012f77a43bf986624d65947fd72"
}
```

## Development

```bash
make format      # ruff format + autofix
make lint        # ruff
make typecheck   # mypy --strict
make test        # pytest
make cov         # pytest with coverage
pre-commit install
```

Tests run against SQLite by default so no database is needed locally. To run them against MySQL
(as CI does), set `DATABASE_URL_OVERRIDE`:

```bash
DATABASE_URL_OVERRIDE="mysql+aiomysql://root:root@127.0.0.1:3306/taskflow_test" pytest
```

### Migrations

```bash
alembic revision --autogenerate -m "add labels to tasks"   # review the generated file!
alembic upgrade head
alembic downgrade -1
alembic check                                               # fails if models and migrations drift
```

## Production notes

- **Secrets:** set a long random `SECRET_KEY`; the app refuses to start in `ENVIRONMENT=production`
  with the default key, a key shorter than 32 chars, `DEBUG=true` or `BCRYPT_ROUNDS < 12`.
- **Docs:** set `DOCS_ENABLED=false` to hide `/docs`, `/redoc` and the OpenAPI schema.
- **Migrations with multiple replicas:** set `RUN_MIGRATIONS=false` on the app containers and run
  `alembic upgrade head` once per deploy (e.g. a Kubernetes Job / release phase).
- **Workers:** tune `WEB_CONCURRENCY` (uvicorn worker processes) and `DB_POOL_SIZE` /
  `DB_MAX_OVERFLOW` together so total connections stay below MySQL's `max_connections`.
- **Reverse proxy:** set `FORWARDED_ALLOW_IPS` to your load balancer's address so client IPs in
  access logs are correct.
- **Probes:** use `/api/v1/health/live` for liveness and `/api/v1/health/ready` for readiness.
- **Time zones:** all timestamps are stored as UTC and returned in ISO-8601 with `Z`; dates
  (`due_date`, `start_date`) are calendar dates and "today" is evaluated in UTC.
