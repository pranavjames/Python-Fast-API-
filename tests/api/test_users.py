from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, User
from tests.conftest import (
    API,
    DEFAULT_PASSWORD,
    AuthHeaders,
    TaskFactory,
    UserFactory,
    days_from_today,
    login,
)

# ---------------------------------------------------------------------------
# Self-service profile
# ---------------------------------------------------------------------------


async def test_get_me(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    user, headers = user_auth
    response = await client.get(f"{API}/users/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert response.json()["email"] == "alice@example.com"


async def test_update_me(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    response = await client.patch(
        f"{API}/users/me",
        headers=headers,
        json={"full_name": "  Alice Johnson  ", "job_title": "Lead", "phone_number": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Alice Johnson"
    assert body["job_title"] == "Lead"
    assert body["phone_number"] is None


async def test_update_me_rejects_null_for_required_field(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.patch(f"{API}/users/me", headers=headers, json={"email": None})
    assert response.status_code == 422


async def test_update_me_cannot_change_role(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.patch(f"{API}/users/me", headers=headers, json={"role": "admin"})
    assert response.status_code == 422


async def test_update_me_rejects_email_taken_by_another_user(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, headers = user_auth
    await make_user(email="taken@example.com")
    response = await client.patch(
        f"{API}/users/me", headers=headers, json={"email": "Taken@example.com"}
    )
    assert response.status_code == 409


async def test_change_password(client: AsyncClient, user_auth: tuple[User, AuthHeaders]) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": DEFAULT_PASSWORD, "new_password": "BrandNew123"},
    )
    assert response.status_code == 204

    await login(client, "alice@example.com", "BrandNew123")
    old = await client.post(
        f"{API}/auth/login",
        data={"username": "alice@example.com", "password": DEFAULT_PASSWORD},
    )
    assert old.status_code == 401


async def test_change_password_requires_correct_current_password(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": "Wrong1234", "new_password": "BrandNew123"},
    )
    assert response.status_code == 401


async def test_change_password_rejects_same_password(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.post(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------


async def test_regular_user_cannot_access_admin_endpoints(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = user_auth
    response = await client.get(f"{API}/users", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_admin_lists_and_filters_users(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, headers = admin_auth
    for i in range(3):
        await make_user(email=f"member{i}@example.com", full_name=f"Member {i}")
    await make_user(email="inactive@example.com", is_active=False)

    page = await client.get(f"{API}/users", headers=headers, params={"size": 2, "page": 1})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2

    search = await client.get(f"{API}/users", headers=headers, params={"search": "member"})
    assert search.json()["total"] == 3

    inactive = await client.get(f"{API}/users", headers=headers, params={"is_active": "false"})
    assert [u["email"] for u in inactive.json()["items"]] == ["inactive@example.com"]

    admins = await client.get(f"{API}/users", headers=headers, params={"role": "admin"})
    assert admins.json()["total"] == 1


async def test_pagination_size_is_bounded(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = admin_auth
    response = await client.get(f"{API}/users", headers=headers, params={"size": 1000})
    assert response.status_code == 422


async def test_admin_creates_user_with_role(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = admin_auth
    response = await client.post(
        f"{API}/users",
        headers=headers,
        json={
            "email": "manager@example.com",
            "password": DEFAULT_PASSWORD,
            "full_name": "Manager",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "admin"


async def test_admin_gets_user_or_404(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, headers = admin_auth
    user, _ = await make_user()

    found = await client.get(f"{API}/users/{user.id}", headers=headers)
    assert found.status_code == 200
    missing = await client.get(f"{API}/users/999999", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_admin_deactivates_user_which_revokes_access(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, admin_headers = admin_auth
    user, user_headers = await make_user()

    response = await client.patch(
        f"{API}/users/{user.id}", headers=admin_headers, json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    denied = await client.get(f"{API}/users/me", headers=user_headers)
    assert denied.status_code == 403


async def test_admin_cannot_demote_or_deactivate_self(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders]
) -> None:
    admin, headers = admin_auth
    demote = await client.patch(f"{API}/users/{admin.id}", headers=headers, json={"role": "user"})
    assert demote.status_code == 422
    deactivate = await client.patch(
        f"{API}/users/{admin.id}", headers=headers, json={"is_active": False}
    )
    assert deactivate.status_code == 422


async def test_admin_deletes_user_and_their_tasks(
    client: AsyncClient,
    admin_auth: tuple[User, AuthHeaders],
    make_user: UserFactory,
    make_task: TaskFactory,
    db_session: AsyncSession,
) -> None:
    _, headers = admin_auth
    user, _ = await make_user()
    await make_task(user)
    await make_task(user)

    response = await client.delete(f"{API}/users/{user.id}", headers=headers)
    assert response.status_code == 204

    remaining = await db_session.scalar(
        select(func.count()).select_from(Task).where(Task.owner_id == user.id)
    )
    assert remaining == 0
    assert (await client.get(f"{API}/users/{user.id}", headers=headers)).status_code == 404


async def test_admin_cannot_delete_self(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders]
) -> None:
    admin, headers = admin_auth
    response = await client.delete(f"{API}/users/{admin.id}", headers=headers)
    assert response.status_code == 422


async def test_admin_assigns_and_lists_user_tasks(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders], make_user: UserFactory
) -> None:
    _, admin_headers = admin_auth
    user, user_headers = await make_user()

    created = await client.post(
        f"{API}/users/{user.id}/tasks",
        headers=admin_headers,
        json={"title": "Quarterly report", "due_date": days_from_today(10)},
    )
    assert created.status_code == 201
    assert created.json()["owner_id"] == user.id

    listed = await client.get(f"{API}/users/{user.id}/tasks", headers=admin_headers)
    assert listed.json()["total"] == 1

    # The assignee sees the task in their own list.
    own = await client.get(f"{API}/tasks", headers=user_headers)
    assert own.json()["items"][0]["title"] == "Quarterly report"


async def test_admin_task_endpoints_404_for_unknown_user(
    client: AsyncClient, admin_auth: tuple[User, AuthHeaders]
) -> None:
    _, headers = admin_auth
    listed = await client.get(f"{API}/users/999999/tasks", headers=headers)
    assert listed.status_code == 404
    created = await client.post(
        f"{API}/users/999999/tasks",
        headers=headers,
        json={"title": "x", "due_date": days_from_today(1)},
    )
    assert created.status_code == 404
