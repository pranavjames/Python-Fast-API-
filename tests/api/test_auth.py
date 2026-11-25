from httpx import AsyncClient

from app.core.security import create_access_token, create_refresh_token
from app.models import User
from tests.conftest import API, DEFAULT_PASSWORD, AuthHeaders, UserFactory

REGISTER_PAYLOAD = {
    "email": "New.User@Example.com",
    "password": DEFAULT_PASSWORD,
    "full_name": "New User",
    "phone_number": "+1 555-123-4567",
    "job_title": "Engineer",
}


async def test_register_creates_user_with_normalised_email(client: AsyncClient) -> None:
    response = await client.post(f"{API}/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert body["full_name"] == "New User"
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "password" not in body and "hashed_password" not in body


async def test_register_rejects_duplicate_email_case_insensitively(client: AsyncClient) -> None:
    await client.post(f"{API}/auth/register", json=REGISTER_PAYLOAD)
    duplicate = {**REGISTER_PAYLOAD, "email": "NEW.USER@example.com"}

    response = await client.post(f"{API}/auth/register", json=duplicate)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    payload = {**REGISTER_PAYLOAD, "password": "onlyletters"}
    response = await client.post(f"{API}/auth/register", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_register_rejects_unknown_fields(client: AsyncClient) -> None:
    payload = {**REGISTER_PAYLOAD, "role": "admin"}
    response = await client.post(f"{API}/auth/register", json=payload)
    assert response.status_code == 422


async def test_register_rejects_invalid_phone(client: AsyncClient) -> None:
    payload = {**REGISTER_PAYLOAD, "phone_number": "call me"}
    response = await client.post(f"{API}/auth/register", json=payload)
    assert response.status_code == 422


async def test_login_returns_token_pair_and_records_login(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    response = await client.post(
        f"{API}/auth/login",
        data={"username": "ALICE@example.com", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0

    me = await client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.json()["last_login_at"] is not None


async def test_login_with_wrong_password_fails(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    response = await client.post(
        f"{API}/auth/login", data={"username": "alice@example.com", "password": "Wrong1234"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_login_with_unknown_email_fails(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/login", data={"username": "ghost@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 401


async def test_inactive_user_cannot_login(client: AsyncClient, make_user: UserFactory) -> None:
    await make_user(email="inactive@example.com", is_active=False)
    response = await client.post(
        f"{API}/auth/login",
        data={"username": "inactive@example.com", "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 403


async def test_refresh_issues_new_tokens(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    user, _ = user_auth
    response = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": create_refresh_token(user.id)}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_refresh_rejects_access_token(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    user, _ = user_auth
    response = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": create_access_token(user.id)}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid token type"


async def test_refresh_token_cannot_access_protected_routes(
    client: AsyncClient, user_auth: tuple[User, AuthHeaders]
) -> None:
    user, _ = user_auth
    headers = {"Authorization": f"Bearer {create_refresh_token(user.id)}"}
    response = await client.get(f"{API}/users/me", headers=headers)
    assert response.status_code == 401


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    response = await client.get(f"{API}/users/me")
    assert response.status_code == 401


async def test_protected_route_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get(f"{API}/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid token"


async def test_token_for_deleted_user_is_rejected(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {create_access_token(999_999)}"}
    response = await client.get(f"{API}/users/me", headers=headers)
    assert response.status_code == 401
