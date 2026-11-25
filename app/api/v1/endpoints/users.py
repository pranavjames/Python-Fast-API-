from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import (
    CurrentAdmin,
    CurrentUser,
    PageParamsDep,
    TaskServiceDep,
    UserServiceDep,
)
from app.models.user import UserRole
from app.schemas.common import ErrorResponse, Page
from app.schemas.task import TaskCreate, TaskFilters, TaskRead
from app.schemas.user import AdminUserCreate, AdminUserUpdate, PasswordChange, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])

_ADMIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse, "description": "Administrator privileges required"},
    404: {"model": ErrorResponse, "description": "User not found"},
}


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserRead, summary="Get the authenticated user's profile")
async def read_me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update the authenticated user's profile",
    responses={409: {"model": ErrorResponse, "description": "Email already in use"}},
)
async def update_me(
    payload: UserUpdate, current_user: CurrentUser, user_service: UserServiceDep
) -> UserRead:
    user = await user_service.update_profile(current_user, payload)
    return UserRead.model_validate(user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the authenticated user's password",
    responses={401: {"model": ErrorResponse, "description": "Current password is incorrect"}},
)
async def change_my_password(
    payload: PasswordChange, current_user: CurrentUser, user_service: UserServiceDep
) -> None:
    await user_service.change_password(current_user, payload)


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Page[UserRead],
    summary="List users (admin)",
    responses=_ADMIN_RESPONSES,
)
async def list_users(
    _: CurrentAdmin,
    user_service: UserServiceDep,
    pagination: PageParamsDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> Page[UserRead]:
    users, total = await user_service.list(
        page=pagination.page,
        size=pagination.size,
        search=search,
        role=role,
        is_active=is_active,
    )
    return Page.create(
        [UserRead.model_validate(u) for u in users], total, pagination.page, pagination.size
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user with a specific role (admin)",
    responses={**_ADMIN_RESPONSES, 409: {"model": ErrorResponse}},
)
async def create_user(
    payload: AdminUserCreate, _: CurrentAdmin, user_service: UserServiceDep
) -> UserRead:
    user = await user_service.create(payload, role=payload.role)
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}", response_model=UserRead, summary="Get a user (admin)", responses=_ADMIN_RESPONSES
)
async def read_user(user_id: int, _: CurrentAdmin, user_service: UserServiceDep) -> UserRead:
    return UserRead.model_validate(await user_service.get(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update a user (admin)",
    responses={**_ADMIN_RESPONSES, 409: {"model": ErrorResponse}},
)
async def update_user(
    user_id: int, payload: AdminUserUpdate, admin: CurrentAdmin, user_service: UserServiceDep
) -> UserRead:
    user = await user_service.admin_update(user_id, payload, acting_user=admin)
    return UserRead.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user and all of their tasks (admin)",
    responses=_ADMIN_RESPONSES,
)
async def delete_user(user_id: int, admin: CurrentAdmin, user_service: UserServiceDep) -> None:
    await user_service.delete(user_id, acting_user=admin)


@router.get(
    "/{user_id}/tasks",
    response_model=Page[TaskRead],
    summary="List a user's tasks (admin)",
    responses=_ADMIN_RESPONSES,
)
async def list_user_tasks(
    user_id: int,
    _: CurrentAdmin,
    user_service: UserServiceDep,
    task_service: TaskServiceDep,
    filters: Annotated[TaskFilters, Query()],
    pagination: PageParamsDep,
) -> Page[TaskRead]:
    await user_service.get(user_id)
    tasks, total = await task_service.list(
        user_id, filters, page=pagination.page, size=pagination.size
    )
    return Page.create(
        [TaskRead.model_validate(t) for t in tasks], total, pagination.page, pagination.size
    )


@router.post(
    "/{user_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a new task to a user (admin)",
    responses={**_ADMIN_RESPONSES, 422: {"model": ErrorResponse}},
)
async def assign_task(
    user_id: int,
    payload: TaskCreate,
    _: CurrentAdmin,
    user_service: UserServiceDep,
    task_service: TaskServiceDep,
) -> TaskRead:
    await user_service.get(user_id)
    task = await task_service.create(user_id, payload)
    return TaskRead.model_validate(task)
