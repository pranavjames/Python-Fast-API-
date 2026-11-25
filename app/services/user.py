from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import AdminUserUpdate, PasswordChange, UserCreate, UserUpdate

logger = get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def get(self, user_id: int) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def list(
        self,
        *,
        page: int,
        size: int,
        search: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[User], int]:
        return await self.users.list(
            page=page, size=size, search=search, role=role, is_active=is_active
        )

    async def create(self, data: UserCreate, *, role: UserRole = UserRole.USER) -> User:
        email = data.email.lower()
        if await self.users.get_by_email(email):
            raise ConflictError("A user with this email already exists")
        user = User(
            email=email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            phone_number=data.phone_number,
            job_title=data.job_title,
            role=role,
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as exc:  # concurrent creation with the same email
            await self.session.rollback()
            raise ConflictError("A user with this email already exists") from exc
        logger.info("User created", extra={"user_id": user.id, "role": role.value})
        return user

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        return await self._apply_update(user, data.model_dump(exclude_unset=True))

    async def admin_update(self, user_id: int, data: AdminUserUpdate, *, acting_user: User) -> User:
        user = await self.get(user_id)
        values = data.model_dump(exclude_unset=True)
        if user.id == acting_user.id:
            if values.get("is_active") is False:
                raise BusinessRuleError("Administrators cannot deactivate their own account")
            if values.get("role", UserRole.ADMIN) != UserRole.ADMIN:
                raise BusinessRuleError("Administrators cannot remove their own admin role")
        return await self._apply_update(user, values)

    async def change_password(self, user: User, data: PasswordChange) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        if verify_password(data.new_password, user.hashed_password):
            raise BusinessRuleError("New password must differ from the current password")
        await self.users.update(user, {"hashed_password": hash_password(data.new_password)})
        await self.session.commit()
        logger.info("Password changed", extra={"user_id": user.id})

    async def delete(self, user_id: int, *, acting_user: User) -> None:
        if user_id == acting_user.id:
            raise BusinessRuleError("Administrators cannot delete their own account")
        user = await self.get(user_id)
        await self.users.delete(user)
        await self.session.commit()
        logger.info("User deleted", extra={"user_id": user_id, "deleted_by": acting_user.id})

    async def _apply_update(self, user: User, values: dict[str, object]) -> User:
        if not values:
            return user
        if "email" in values:
            email = str(values["email"]).lower()
            existing = await self.users.get_by_email(email)
            if existing is not None and existing.id != user.id:
                raise ConflictError("A user with this email already exists")
            values["email"] = email
        try:
            await self.users.update(user, values)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A user with this email already exists") from exc
        return user
