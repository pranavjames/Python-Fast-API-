from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("S3cretPass")
    assert hashed != "S3cretPass"
    assert verify_password("S3cretPass", hashed)
    assert not verify_password("WrongPass1", hashed)


def test_verify_password_handles_malformed_hash() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_round_trip() -> None:
    payload = decode_token(create_access_token(42), TokenType.ACCESS)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"
    assert payload["jti"]


def test_token_type_is_enforced() -> None:
    with pytest.raises(AuthenticationError, match="Invalid token type"):
        decode_token(create_refresh_token(1), TokenType.ACCESS)


def test_expired_token_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "1",
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(AuthenticationError, match="expired"):
        decode_token(token, TokenType.ACCESS)


def test_token_signed_with_other_key_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "1", "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        "a-completely-different-secret-key-value",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError, match="Invalid token"):
        decode_token(token, TokenType.ACCESS)


def test_token_missing_required_claims_is_rejected() -> None:
    token = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(AuthenticationError):
        decode_token(token, TokenType.ACCESS)
