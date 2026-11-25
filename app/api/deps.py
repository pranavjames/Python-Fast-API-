"""Reusable FastAPI dependencies: DB session, services, authentication, pagination."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import PermissionDeniedError
from app.core.security import TokenType, decode_token
from app.db.session import get_session
from app.models.user import User
from app.services.auth import AuthService
from app.services.task import TaskService
from app.services.user import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(session)


def get_user_service(session: SessionDep) -> UserService:
    return UserService(session)


def get_task_service(session: SessionDep) -> TaskService:
    return TaskService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], auth_service: AuthServiceDep
) -> User:
    payload = decode_token(token, TokenType.ACCESS)
    return await auth_service.get_active_user_from_subject(payload["sub"])


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise PermissionDeniedError("Administrator privileges required")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    size: int


def get_page_params(
    page: Annotated[int, Query(ge=1, description="Page number (1-based)")] = 1,
    size: Annotated[
        int, Query(ge=1, le=settings.MAX_PAGE_SIZE, description="Items per page")
    ] = settings.DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, size=size)


PageParamsDep = Annotated[PageParams, Depends(get_page_params)]
