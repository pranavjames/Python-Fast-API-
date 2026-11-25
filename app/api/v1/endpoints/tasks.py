from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, PageParamsDep, TaskServiceDep
from app.schemas.common import ErrorResponse, Page
from app.schemas.task import (
    TaskCreate,
    TaskFilters,
    TaskRead,
    TaskStatusUpdate,
    TaskSummary,
    TaskTimeline,
    TaskUpdate,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Task not found"}
}
_RULE_VIOLATION: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Validation or business rule"}
}


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task with its own completion date",
    responses=_RULE_VIOLATION,
)
async def create_task(
    payload: TaskCreate, current_user: CurrentUser, task_service: TaskServiceDep
) -> TaskRead:
    task = await task_service.create(current_user.id, payload)
    return TaskRead.model_validate(task)


@router.get("", response_model=Page[TaskRead], summary="List, filter and sort your tasks")
async def list_tasks(
    current_user: CurrentUser,
    task_service: TaskServiceDep,
    filters: Annotated[TaskFilters, Query()],
    pagination: PageParamsDep,
) -> Page[TaskRead]:
    tasks, total = await task_service.list(
        current_user.id, filters, page=pagination.page, size=pagination.size
    )
    return Page.create(
        [TaskRead.model_validate(t) for t in tasks], total, pagination.page, pagination.size
    )


@router.get(
    "/timeline",
    response_model=TaskTimeline,
    summary="Open tasks grouped by due date",
    description=(
        "Returns overdue open tasks plus open tasks due within the requested window, grouped "
        "by due date. Defaults to today through the next 30 days."
    ),
    responses=_RULE_VIOLATION,
)
async def get_timeline(
    current_user: CurrentUser,
    task_service: TaskServiceDep,
    from_date: Annotated[date | None, Query(description="Window start (default: today)")] = None,
    to_date: Annotated[date | None, Query(description="Window end (default: +30 days)")] = None,
) -> TaskTimeline:
    return await task_service.timeline(current_user.id, from_date, to_date)


@router.get("/summary", response_model=TaskSummary, summary="Task counts by status and deadline")
async def get_summary(current_user: CurrentUser, task_service: TaskServiceDep) -> TaskSummary:
    return await task_service.summary(current_user.id)


@router.get("/{task_id}", response_model=TaskRead, summary="Get a task", responses=_NOT_FOUND)
async def get_task(
    task_id: int, current_user: CurrentUser, task_service: TaskServiceDep
) -> TaskRead:
    return TaskRead.model_validate(await task_service.get(task_id, current_user.id))


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    summary="Partially update a task",
    responses={**_NOT_FOUND, **_RULE_VIOLATION},
)
async def update_task(
    task_id: int, payload: TaskUpdate, current_user: CurrentUser, task_service: TaskServiceDep
) -> TaskRead:
    task = await task_service.update(task_id, current_user.id, payload)
    return TaskRead.model_validate(task)


@router.patch(
    "/{task_id}/status",
    response_model=TaskRead,
    summary="Change a task's status",
    responses={**_NOT_FOUND, **_RULE_VIOLATION},
)
async def change_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    current_user: CurrentUser,
    task_service: TaskServiceDep,
) -> TaskRead:
    task = await task_service.change_status(task_id, current_user.id, payload.status)
    return TaskRead.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
    responses=_NOT_FOUND,
)
async def delete_task(
    task_id: int, current_user: CurrentUser, task_service: TaskServiceDep
) -> None:
    await task_service.delete(task_id, current_user.id)
