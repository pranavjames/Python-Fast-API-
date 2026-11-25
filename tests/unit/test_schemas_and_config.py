from datetime import date

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.schemas.task import TaskCreate, TaskFilters, TaskUpdate
from app.schemas.user import UserCreate


@pytest.mark.parametrize(
    ("password", "valid"),
    [
        ("Abcdefg1", True),
        ("short1A", False),  # too short
        ("abcdefgh", False),  # no digit
        ("12345678", False),  # no letter
        ("a1" + "é" * 36, False),  # 74 bytes: exceeds bcrypt limit
    ],
)
def test_password_policy(password: str, valid: bool) -> None:
    payload = {"email": "a@example.com", "full_name": "A", "password": password}
    if valid:
        UserCreate.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            UserCreate.model_validate(payload)


def test_task_create_rejects_start_after_due() -> None:
    with pytest.raises(ValidationError, match="start_date must be on or before due_date"):
        TaskCreate(title="x", start_date=date(2030, 1, 2), due_date=date(2030, 1, 1))


def test_task_update_tracks_explicitly_set_fields() -> None:
    update = TaskUpdate.model_validate({"description": None})
    assert update.model_dump(exclude_unset=True) == {"description": None}


@pytest.mark.parametrize("field", ["title", "due_date", "status", "priority"])
def test_task_update_rejects_null_for_required_columns(field: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        TaskUpdate.model_validate({field: None})


def test_task_filters_reject_inverted_range() -> None:
    with pytest.raises(ValidationError):
        TaskFilters(due_from=date(2030, 2, 1), due_to=date(2030, 1, 1))


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(CORS_ORIGINS="https://a.example.com, https://b.example.com")  # type: ignore[arg-type]
    assert settings.CORS_ORIGINS == ["https://a.example.com", "https://b.example.com"]


def test_mysql_url_escapes_password() -> None:
    settings = Settings(
        DATABASE_URL_OVERRIDE=None, MYSQL_PASSWORD=SecretStr("p@ss/word"), MYSQL_HOST="db"
    )
    assert settings.DATABASE_URL.startswith("mysql+aiomysql://taskflow:p%40ss%2Fword@db:3306/")


@pytest.mark.parametrize(
    "overrides",
    [
        {},  # default insecure secret
        {"SECRET_KEY": SecretStr("too-short")},
        {"SECRET_KEY": SecretStr("x" * 40), "DEBUG": True},
        {"SECRET_KEY": SecretStr("x" * 40), "BCRYPT_ROUNDS": 4},
    ],
)
def test_production_settings_guardrails(overrides: dict) -> None:
    base = {
        "ENVIRONMENT": "production",
        "BCRYPT_ROUNDS": 12,
        "SECRET_KEY": SecretStr("change-me-in-production"),
    }
    with pytest.raises(ValidationError):
        Settings(**{**base, **overrides})


def test_production_settings_accept_secure_config() -> None:
    Settings(
        ENVIRONMENT="production", SECRET_KEY=SecretStr("x" * 40), BCRYPT_ROUNDS=12, DEBUG=False
    )
