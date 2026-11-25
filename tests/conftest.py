"""Shared test fixtures.

Tests run against an isolated SQLite database so they need no external services;
the same suite runs against MySQL in CI by setting DATABASE_URL_OVERRIDE.
"""

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / f"taskflow_test_{os.getpid()}.db"

# Must be configured before any application module is imported.
os.environ.setdefault("DATABASE_URL_OVERRIDE", f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}")
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionFactory, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Task, User, UserRole  # noqa: E402
from app.models.task import today_utc  # noqa: E402

API = "/api/v1"
DEFAULT_PASSWORD = "Str0ngPassw0rd"

AuthHeaders = dict[str, str]


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    _TEST_DB.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> AuthHeaders:
    response = await client.post(
        f"{API}/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


UserFactory = Callable[..., Awaitable[tuple[User, AuthHeaders]]]


@pytest.fixture
def make_user(client: AsyncClient, db_session: AsyncSession) -> UserFactory:
    counter = 0

    async def factory(
        *,
        email: str | None = None,
        role: UserRole = UserRole.USER,
        is_active: bool = True,
        **fields: Any,
    ) -> tuple[User, AuthHeaders]:
        nonlocal counter
        counter += 1
        user = User(
            email=email or f"user{counter}@example.com",
            hashed_password=hash_password(DEFAULT_PASSWORD),
            full_name=fields.pop("full_name", f"User {counter}"),
            role=role,
            is_active=is_active,
            **fields,
        )
        db_session.add(user)
        await db_session.commit()
        headers = await login(client, user.email) if is_active else {}
        return user, headers

    return factory


@pytest.fixture
async def user_auth(make_user: UserFactory) -> tuple[User, AuthHeaders]:
    return await make_user(email="alice@example.com", full_name="Alice Smith")


@pytest.fixture
async def admin_auth(make_user: UserFactory) -> tuple[User, AuthHeaders]:
    return await make_user(email="admin@example.com", role=UserRole.ADMIN, full_name="Admin")


TaskFactory = Callable[..., Awaitable[Task]]


@pytest.fixture
def make_task(db_session: AsyncSession) -> TaskFactory:
    """Insert a task directly, bypassing API rules (e.g. to create overdue tasks)."""

    async def factory(owner: User, *, due_in_days: int = 7, **fields: Any) -> Task:
        task = Task(
            owner_id=owner.id,
            title=fields.pop("title", "Task"),
            due_date=today_utc() + timedelta(days=due_in_days),
            **fields,
        )
        db_session.add(task)
        await db_session.commit()
        return task

    return factory


def days_from_today(days: int) -> str:
    return (today_utc() + timedelta(days=days)).isoformat()


def iso(value: date) -> str:
    return value.isoformat()
