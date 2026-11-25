import re
from datetime import datetime
from typing import Annotated, ClassVar

from pydantic import AfterValidator, EmailStr, Field

from app.core.security import BCRYPT_MAX_BYTES
from app.models.user import UserRole
from app.schemas.common import APIModel, ORMModel, PatchModel

_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{6,19}$")


def _validate_password_strength(value: str) -> str:
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must not exceed {BCRYPT_MAX_BYTES} bytes")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


def _validate_phone(value: str | None) -> str | None:
    if value is not None and not _PHONE_RE.match(value):
        raise ValueError("Invalid phone number format")
    return value


Password = Annotated[
    str, Field(min_length=8, max_length=64), AfterValidator(_validate_password_strength)
]
FullName = Annotated[str, Field(min_length=1, max_length=100)]
PhoneNumber = Annotated[
    str | None, Field(default=None, max_length=20), AfterValidator(_validate_phone)
]
JobTitle = Annotated[str | None, Field(default=None, max_length=100)]


class UserCreate(APIModel):
    email: EmailStr
    password: Password
    full_name: FullName
    phone_number: PhoneNumber = None
    job_title: JobTitle = None


class AdminUserCreate(UserCreate):
    role: UserRole = UserRole.USER


class UserUpdate(PatchModel):
    """Fields a user may change on their own profile."""

    non_nullable_fields: ClassVar[tuple[str, ...]] = ("email", "full_name")

    email: EmailStr | None = None
    full_name: FullName | None = None
    phone_number: PhoneNumber = None
    job_title: JobTitle = None


class AdminUserUpdate(UserUpdate):
    """Fields only administrators may change."""

    non_nullable_fields: ClassVar[tuple[str, ...]] = ("email", "full_name", "role", "is_active")

    role: UserRole | None = None
    is_active: bool | None = None


class PasswordChange(APIModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class UserRead(ORMModel):
    id: int
    email: EmailStr
    full_name: str
    phone_number: str | None
    job_title: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
