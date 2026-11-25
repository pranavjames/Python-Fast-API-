from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.models import TaskPriority, TaskStatus, User
from app.models.task import today_utc
from tests.conftest import API, AuthHeaders, TaskFactory, UserFactory, days_from_today


async def _create(client: AsyncClient, headers: AuthHeaders, **payload: object) -> dict:
    body = {"title": "Write docs", "due_date": days_from_today(5), **payload}
    response = await client.post(f"{API}/tasks", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_task_with_timeline(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    user, headers = user_auth
    task = await _create(
        client,
        headers,
        title="  Prepare release  ",
        description="Cut v1.0",
        priority="high",
        start_date=days_from_today(1),
        due_date=days_from_today(3),
    )

    assert task["owner_id"] == user.id
    assert task["title"] == "Prepare release"
    assert task["status"] == "pending"
    assert task["priority"] == "high"
    assert task["start_date"] == days_from_today(1)
    assert task["due_date"] == days_from_today(3)
    assert task["days_remaining"] == 3
    assert task["is_overdue"] is False
    assert task["completed_at"] is None
    assert task["created_at"].endswith(("Z", "+00:00"))


async def test_each_task_keeps_its_own_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    due_dates = [days_from_today(d) for d in (1, 14, 60)]
    for i, due in enumerate(due_dates):
        await _create(client, headers, title=f"Task {i}", due_date=due)

    response = await client.get(f"{API}/tasks", headers=headers)
    assert [t["due_date"] for t in response.json()["items"]] == due_dates


async def test_create_task_due_today_is_allowed(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    task = await _create(client, headers, due_date=days_from_today(0))
    assert task["days_remaining"] == 0


async def test_create_task_rejects_past_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/tasks", headers=headers, json={"title": "Late", "due_date": days_from_today(-1)}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violation"


async def test_create_task_rejects_start_after_due(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/tasks",
        headers=headers,
        json={"title": "x", "start_date": days_from_today(5), "due_date": days_from_today(2)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_create_task_rejects_closed_status(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], status: str
) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/tasks",
        headers=headers,
        json={"title": "x", "due_date": days_from_today(1), "status": status},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"due_date": "2030-01-01"},
        {"title": "", "due_date": "2030-01-01"},
        {"title": "x" * 201, "due_date": "2030-01-01"},
        {"title": "x", "due_date": "not-a-date"},
        {"title": "x", "due_date": "2030-01-01", "priority": "critical"},
    ],
)
async def test_create_task_validates_payload(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], payload: dict
) -> None:
    _, headers = user_auth
    response = await client.post(f"{API}/tasks", headers=headers, json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Read / ownership
# ---------------------------------------------------------------------------


async def test_get_task(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    task = await _create(client, headers)
    response = await client.get(f"{API}/tasks/{task['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == task


async def test_users_cannot_see_or_modify_each_others_tasks(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, alice_headers = user_auth
    _, bob_headers = await make_user(email="bob@example.com")
    task = await _create(client, alice_headers)
    url = f"{API}/tasks/{task['id']}"

    assert (await client.get(url, headers=bob_headers)).status_code == 404
    assert (await client.patch(url, headers=bob_headers, json={"title": "x"})).status_code == 404
    assert (await client.delete(url, headers=bob_headers)).status_code == 404
    assert (await client.get(f"{API}/tasks", headers=bob_headers)).json()["total"] == 0


# ---------------------------------------------------------------------------
# List: filtering, sorting, pagination
# ---------------------------------------------------------------------------


async def test_list_filters(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    await make_task(user, title="Overdue bug", due_in_days=-2, priority=TaskPriority.URGENT)
    await make_task(user, title="Done", due_in_days=-5, status=TaskStatus.COMPLETED)
    await make_task(user, title="Design review", due_in_days=3, status=TaskStatus.IN_PROGRESS)
    await make_task(user, title="Budget 100%_plan", due_in_days=20, priority=TaskPriority.LOW)

    async def titles(**params: object) -> list[str]:
        response = await client.get(f"{API}/tasks", headers=headers, params=params)
        assert response.status_code == 200, response.text
        return [t["title"] for t in response.json()["items"]]

    assert await titles(status="in_progress") == ["Design review"]
    assert await titles(status=["pending", "completed"]) == [
        "Done",
        "Overdue bug",
        "Budget 100%_plan",
    ]
    assert await titles(priority="urgent") == ["Overdue bug"]
    assert await titles(overdue="true") == ["Overdue bug"]
    assert await titles(overdue="false") == ["Done", "Design review", "Budget 100%_plan"]
    assert await titles(due_from=days_from_today(0), due_to=days_from_today(10)) == [
        "Design review"
    ]
    assert await titles(search="REVIEW") == ["Design review"]
    # LIKE wildcards in the search term are matched literally.
    assert await titles(search="100%_") == ["Budget 100%_plan"]
    assert await titles(search="%") == ["Budget 100%_plan"]


async def test_list_rejects_inverted_due_range(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.get(
        f"{API}/tasks",
        headers=headers,
        params={"due_from": days_from_today(5), "due_to": days_from_today(1)},
    )
    assert response.status_code == 422


async def test_list_sorting(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    await make_task(user, title="B", priority=TaskPriority.LOW, due_in_days=1)
    await make_task(user, title="C", priority=TaskPriority.URGENT, due_in_days=3)
    await make_task(user, title="A", priority=TaskPriority.MEDIUM, due_in_days=2)

    async def order(**params: str) -> list[str]:
        response = await client.get(f"{API}/tasks", headers=headers, params=params)
        return [t["title"] for t in response.json()["items"]]

    assert await order() == ["B", "A", "C"]  # default: due_date ascending
    assert await order(sort_by="due_date", sort_order="desc") == ["C", "A", "B"]
    assert await order(sort_by="priority", sort_order="desc") == ["C", "A", "B"]
    assert await order(sort_by="title") == ["A", "B", "C"]


async def test_list_pagination(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    for day in range(1, 6):
        await make_task(user, title=f"T{day}", due_in_days=day)

    response = await client.get(f"{API}/tasks", headers=headers, params={"page": 2, "size": 2})
    body = response.json()
    assert body["total"] == 5
    assert body["pages"] == 3
    assert body["page"] == 2
    assert [t["title"] for t in body["items"]] == ["T3", "T4"]

    beyond = await client.get(f"{API}/tasks", headers=headers, params={"page": 9, "size": 2})
    assert beyond.json()["items"] == []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def test_update_task(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    task = await _create(client, headers)

    response = await client.patch(
        f"{API}/tasks/{task['id']}",
        headers=headers,
        json={"title": "Write better docs", "due_date": days_from_today(9), "description": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Write better docs"
    assert body["due_date"] == days_from_today(9)
    assert body["days_remaining"] == 9
    assert body["priority"] == task["priority"]


async def test_update_rejects_due_date_in_past(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    task = await _create(client, headers)
    response = await client.patch(
        f"{API}/tasks/{task['id']}", headers=headers, json={"due_date": days_from_today(-1)}
    )
    assert response.status_code == 422


async def test_update_allows_editing_overdue_task_without_moving_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    task = await make_task(user, due_in_days=-3)
    response = await client.patch(
        f"{API}/tasks/{task.id}", headers=headers, json={"title": "Still late"}
    )
    assert response.status_code == 200
    assert response.json()["is_overdue"] is True
    assert response.json()["days_remaining"] == -3


async def test_update_validates_start_against_existing_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    task = await _create(client, headers, due_date=days_from_today(2))
    response = await client.patch(
        f"{API}/tasks/{task['id']}", headers=headers, json={"start_date": days_from_today(4)}
    )
    assert response.status_code == 422


async def test_update_rejects_null_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    task = await _create(client, headers)
    response = await client.patch(
        f"{API}/tasks/{task['id']}", headers=headers, json={"due_date": None}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Status lifecycle
# ---------------------------------------------------------------------------


async def test_status_lifecycle(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    task = await _create(client, headers)
    url = f"{API}/tasks/{task['id']}/status"

    started = await client.patch(url, headers=headers, json={"status": "in_progress"})
    assert started.json()["status"] == "in_progress"

    completed = (await client.patch(url, headers=headers, json={"status": "completed"})).json()
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
    assert completed["days_remaining"] is None
    assert completed["is_overdue"] is False

    reopened = (await client.patch(url, headers=headers, json={"status": "pending"})).json()
    assert reopened["completed_at"] is None
    assert reopened["days_remaining"] == 5


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (TaskStatus.CANCELLED, "completed"),
        (TaskStatus.CANCELLED, "in_progress"),
        (TaskStatus.COMPLETED, "cancelled"),
    ],
)
async def test_invalid_status_transitions(
    client: AsyncClient,
    user_auth: tuple[User, AuthHeaders],
    make_task: TaskFactory,
    initial: TaskStatus,
    target: str,
) -> None:
    user, headers = user_auth
    task = await make_task(user, status=initial)
    response = await client.patch(
        f"{API}/tasks/{task.id}/status", headers=headers, json={"status": target}
    )
    assert response.status_code == 422
    assert "Cannot change task status" in response.json()["error"]["message"]


async def test_status_change_via_general_update_sets_completed_at(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    task = await _create(client, headers)
    response = await client.patch(
        f"{API}/tasks/{task['id']}", headers=headers, json={"status": "completed"}
    )
    assert response.json()["completed_at"] is not None


async def test_completing_overdue_task_clears_overdue_flag(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    task = await make_task(user, due_in_days=-1)
    response = await client.patch(
        f"{API}/tasks/{task.id}/status", headers=headers, json={"status": "completed"}
    )
    assert response.json()["is_overdue"] is False


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_task(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    task = await _create(client, headers)

    response = await client.delete(f"{API}/tasks/{task['id']}", headers=headers)
    assert response.status_code == 204
    assert (await client.get(f"{API}/tasks/{task['id']}", headers=headers)).status_code == 404


# ---------------------------------------------------------------------------
# Timeline & summary
# ---------------------------------------------------------------------------


async def test_timeline_groups_open_tasks_by_due_date(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    await make_task(user, title="Overdue", due_in_days=-1)
    await make_task(user, title="Today", due_in_days=0)
    await make_task(user, title="Soon low", due_in_days=2, priority=TaskPriority.LOW)
    await make_task(user, title="Soon urgent", due_in_days=2, priority=TaskPriority.URGENT)
    await make_task(user, title="Closed", due_in_days=2, status=TaskStatus.COMPLETED)
    await make_task(user, title="Far away", due_in_days=90)

    response = await client.get(f"{API}/tasks/timeline", headers=headers)

    assert response.status_code == 200
    body = response.json()
    today = today_utc()
    assert body["from_date"] == today.isoformat()
    assert body["to_date"] == (today + timedelta(days=30)).isoformat()
    assert [t["title"] for t in body["overdue"]] == ["Overdue"]
    assert [(d["due_date"], d["count"]) for d in body["days"]] == [
        (days_from_today(0), 1),
        (days_from_today(2), 2),
    ]
    # Within a day, higher priority comes first.
    assert [t["title"] for t in body["days"][1]["tasks"]] == ["Soon urgent", "Soon low"]


async def test_timeline_custom_window(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    await make_task(user, title="Far away", due_in_days=90)
    response = await client.get(
        f"{API}/tasks/timeline",
        headers=headers,
        params={"from_date": days_from_today(80), "to_date": days_from_today(100)},
    )
    assert [d["due_date"] for d in response.json()["days"]] == [days_from_today(90)]


@pytest.mark.parametrize(
    "params",
    [
        {"from_date": days_from_today(5), "to_date": days_from_today(1)},
        {"from_date": days_from_today(0), "to_date": days_from_today(400)},
    ],
)
async def test_timeline_rejects_invalid_window(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], params: dict
) -> None:
    _, headers = user_auth
    response = await client.get(f"{API}/tasks/timeline", headers=headers, params=params)
    assert response.status_code == 422


async def test_summary(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_task: TaskFactory
) -> None:
    user, headers = user_auth
    await make_task(user, due_in_days=-3)  # pending, overdue
    await make_task(user, due_in_days=0, status=TaskStatus.IN_PROGRESS)  # due today
    await make_task(user, due_in_days=5)  # due this week
    await make_task(user, due_in_days=30)
    await make_task(user, due_in_days=-1, status=TaskStatus.COMPLETED)
    await make_task(user, due_in_days=1, status=TaskStatus.CANCELLED)

    response = await client.get(f"{API}/tasks/summary", headers=headers)

    assert response.json() == {
        "total": 6,
        "pending": 3,
        "in_progress": 1,
        "completed": 1,
        "cancelled": 1,
        "overdue": 1,
        "due_today": 1,
        "due_next_7_days": 2,
    }


async def test_summary_for_user_without_tasks(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.get(f"{API}/tasks/summary", headers=headers)
    assert response.json()["total"] == 0
    assert response.json()["overdue"] == 0
