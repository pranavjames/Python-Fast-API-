from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import register_exception_handlers
from app.db.base import UTCDateTime
from app.middleware.request_context import RequestContextMiddleware
from app.models import Task, TaskStatus
from app.models.task import today_utc


async def test_unhandled_exception_returns_json_500_with_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/boom", headers={"X-Request-ID": "req-1"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-1"
    body = response.json()
    assert body == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred"},
        "request_id": "req-1",
    }
    assert "secret" not in response.text


def test_utc_datetime_normalises_to_utc() -> None:
    column_type = UTCDateTime()
    ist = timezone(timedelta(hours=5, minutes=30))
    stored = column_type.process_bind_param(datetime(2030, 1, 1, 12, 0, tzinfo=ist), None)  # type: ignore[arg-type]
    assert stored == datetime(2030, 1, 1, 6, 30)
    loaded = column_type.process_result_value(stored, None)  # type: ignore[arg-type]
    assert loaded is not None and loaded.tzinfo is UTC


def test_utc_datetime_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="Naive"):
        UTCDateTime().process_bind_param(datetime(2030, 1, 1), None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "due_offset", "overdue", "remaining"),
    [
        (TaskStatus.PENDING, -2, True, -2),
        (TaskStatus.IN_PROGRESS, 0, False, 0),
        (TaskStatus.PENDING, 3, False, 3),
        (TaskStatus.COMPLETED, -2, False, None),
        (TaskStatus.CANCELLED, -2, False, None),
    ],
)
def test_task_deadline_properties(
    status: TaskStatus, due_offset: int, overdue: bool, remaining: int | None
) -> None:
    due: date = today_utc() + timedelta(days=due_offset)
    task = Task(title="t", owner_id=1, status=status, due_date=due)
    assert task.is_overdue is overdue
    assert task.days_remaining == remaining
