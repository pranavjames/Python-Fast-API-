from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    SQLColumnExpression,
    and_,
    case,
    func,
    or_,
    select,
)

from app.models.task import Task, TaskPriority, TaskStatus
from app.repositories.base import BaseRepository
from app.schemas.task import SortOrder, TaskFilters, TaskSortField

OPEN_STATUSES = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)

# Explicit ranks so ordering is semantic and identical on every database backend.
_PRIORITY_RANK = case(
    {p: rank for rank, p in enumerate(TaskPriority)}, value=Task.priority, else_=-1
)
_STATUS_RANK = case({s: rank for rank, s in enumerate(TaskStatus)}, value=Task.status, else_=-1)


@dataclass(frozen=True, slots=True)
class TaskCounts:
    total: int
    pending: int
    in_progress: int
    completed: int
    cancelled: int
    overdue: int
    due_today: int
    due_next_7_days: int


def _is_open() -> ColumnElement[bool]:
    return Task.status.in_(OPEN_STATUSES)


class TaskRepository(BaseRepository[Task]):
    model = Task

    async def get_for_owner(self, task_id: int, owner_id: int) -> Task | None:
        stmt = select(Task).where(Task.id == task_id, Task.owner_id == owner_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_owner(
        self, owner_id: int, filters: TaskFilters, *, today: date, page: int, size: int
    ) -> tuple[Sequence[Task], int]:
        stmt = self._apply_filters(select(Task).where(Task.owner_id == owner_id), filters, today)
        stmt = self._apply_sorting(stmt, filters)
        return await self.paginate(stmt, page=page, size=size)

    async def list_open_due_between(self, owner_id: int, start: date, end: date) -> Sequence[Task]:
        stmt = (
            select(Task)
            .where(Task.owner_id == owner_id, _is_open(), Task.due_date.between(start, end))
            .order_by(Task.due_date, _PRIORITY_RANK.desc(), Task.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_overdue(self, owner_id: int, today: date) -> Sequence[Task]:
        stmt = (
            select(Task)
            .where(Task.owner_id == owner_id, _is_open(), Task.due_date < today)
            .order_by(Task.due_date, _PRIORITY_RANK.desc(), Task.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_for_owner(self, owner_id: int, today: date) -> TaskCounts:
        def count_where(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
            return func.coalesce(func.sum(case((and_(*conditions), 1), else_=0)), 0)

        stmt = select(
            func.count(Task.id),
            count_where(Task.status == TaskStatus.PENDING),
            count_where(Task.status == TaskStatus.IN_PROGRESS),
            count_where(Task.status == TaskStatus.COMPLETED),
            count_where(Task.status == TaskStatus.CANCELLED),
            count_where(_is_open(), Task.due_date < today),
            count_where(_is_open(), Task.due_date == today),
            count_where(_is_open(), Task.due_date.between(today, today + timedelta(days=7))),
        ).where(Task.owner_id == owner_id)
        row = (await self.session.execute(stmt)).one()
        return TaskCounts(*(int(value) for value in row))

    @staticmethod
    def _apply_filters(stmt: Select[Task], filters: TaskFilters, today: date) -> Select[Task]:
        if filters.status:
            stmt = stmt.where(Task.status.in_(filters.status))
        if filters.priority:
            stmt = stmt.where(Task.priority.in_(filters.priority))
        if filters.due_from:
            stmt = stmt.where(Task.due_date >= filters.due_from)
        if filters.due_to:
            stmt = stmt.where(Task.due_date <= filters.due_to)
        if filters.overdue is True:
            stmt = stmt.where(_is_open(), Task.due_date < today)
        elif filters.overdue is False:
            stmt = stmt.where(or_(~_is_open(), Task.due_date >= today))
        if filters.search:
            stmt = stmt.where(
                or_(
                    Task.title.icontains(filters.search, autoescape=True),
                    Task.description.icontains(filters.search, autoescape=True),
                )
            )
        return stmt

    @staticmethod
    def _apply_sorting(stmt: Select[Task], filters: TaskFilters) -> Select[Task]:
        column: SQLColumnExpression[Any] = {
            TaskSortField.DUE_DATE: Task.due_date,
            TaskSortField.PRIORITY: _PRIORITY_RANK,
            TaskSortField.CREATED_AT: Task.created_at,
            TaskSortField.TITLE: Task.title,
            TaskSortField.STATUS: _STATUS_RANK,
        }[filters.sort_by]
        ordered = column.desc() if filters.sort_order == SortOrder.DESC else column.asc()
        # Task.id as tie-breaker keeps pagination stable.
        return stmt.order_by(ordered, Task.id)
