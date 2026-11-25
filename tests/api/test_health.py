from httpx import AsyncClient

from tests.conftest import API


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_checks_database(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_generates_request_id_and_security_headers(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health/live")
    assert len(response.headers["X-Request-ID"]) == 32
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_propagates_valid_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health/live", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


async def test_replaces_malformed_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health/live", headers={"X-Request-ID": "bad id\x01"})
    assert response.headers["X-Request-ID"] != "bad id\x01"


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get(f"{API}/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert body["request_id"] == response.headers["X-Request-ID"]
