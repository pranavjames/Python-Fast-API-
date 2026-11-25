from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.task import TaskPriority, TaskStatus
from app.schemas.common import APIModel, ORMModel, PatchModel


class TaskSortField(StrEnum):
    DUE_DATE = "due_date"
    PRIORITY = "priority"
    CREATED_AT = "created_at"
    TITLE = "title"
    STATUS = "status"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class TaskCreate(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    start_date: date | None = None
    due_date: date = Field(description="Date by which the task must be completed")

    @model_validator(mode="after")
    def _check_timeline(self) -> Self:
        if self.start_date and self.start_date > self.due_date:
            raise ValueError("start_date must be on or before due_date")
        return self


class TaskUpdate(PatchModel):
    non_nullable_fields: ClassVar[tuple[str, ...]] = ("title", "priority", "status", "due_date")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    start_date: date | None = None
    due_date: date | None = None


class TaskStatusUpdate(APIModel):
    status: TaskStatus


class TaskRead(ORMModel):
    id: int
    owner_id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    start_date: date | None
    due_date: date
    completed_at: datetime | None
    is_overdue: bool
    days_remaining: int | None = Field(
        description="Days left until due date (negative if overdue, null when closed)"
    )
    created_at: datetime
    updated_at: datetime


class TaskFilters(BaseModel):
    """Query-string filters for task listings (bound with ``Annotated[TaskFilters, Query()]``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: list[TaskStatus] | None = None
    priority: list[TaskPriority] | None = None
    due_from: date | None = None
    due_to: date | None = None
    overdue: bool | None = Field(
        default=None, description="true: only overdue open tasks; false: exclude them"
    )
    search: str | None = Field(default=None, max_length=100, description="Title/description")
    sort_by: TaskSortField = TaskSortField.DUE_DATE
    sort_order: SortOrder = SortOrder.ASC

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.due_from and self.due_to and self.due_from > self.due_to:
            raise ValueError("due_from must be on or before due_to")
        return self


class TimelineDay(ORMModel):
    due_date: date
    count: int
    tasks: list[TaskRead]


class TaskTimeline(ORMModel):
    from_date: date
    to_date: date
    overdue: list[TaskRead] = Field(description="Open tasks whose due date has already passed")
    days: list[TimelineDay] = Field(description="Open tasks grouped by due date, ascending")


class TaskSummary(ORMModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    cancelled: int
    overdue: int
    due_today: int
    due_next_7_days: int
