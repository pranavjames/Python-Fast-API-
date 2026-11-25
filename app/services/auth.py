from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.base import utcnow
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.user import UserCreate
from app.services.user import UserService

logger = get_logger(__name__)

# Verified against when the user does not exist so that response timing does not
# reveal whether an email address is registered.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, data: UserCreate) -> User:
        return await UserService(self.session).create(data)

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.users.get_by_email(email)
        if user is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("Incorrect email or password")
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise PermissionDeniedError("User account is inactive")

        await self.users.update(user, {"last_login_at": utcnow()})
        await self.session.commit()
        logger.info("User logged in", extra={"user_id": user.id})
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, TokenType.REFRESH)
        user = await self.get_active_user_from_subject(payload["sub"])
        return self._issue_tokens(user)

    async def get_active_user_from_subject(self, subject: str) -> User:
        try:
            user_id = int(subject)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("Invalid token subject") from exc

        user = await self.users.get(user_id)
        if user is None:
            raise AuthenticationError("User no longer exists")
        if not user.is_active:
            raise PermissionDeniedError("User account is inactive")
        return user

    @staticmethod
    def _issue_tokens(user: User) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
