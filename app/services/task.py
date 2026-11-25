from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.task import Task, TaskStatus, today_utc
from app.repositories.task import TaskRepository
from app.schemas.task import (
    TaskCreate,
    TaskFilters,
    TaskRead,
    TaskSummary,
    TaskTimeline,
    TaskUpdate,
    TimelineDay,
)

logger = get_logger(__name__)

DEFAULT_TIMELINE_DAYS = 30
MAX_TIMELINE_DAYS = 366

# Allowed status changes. Closed tasks must be explicitly reopened before moving on.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset({TaskStatus.PENDING, TaskStatus.IN_PROGRESS}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.PENDING}),
}


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tasks = TaskRepository(session)

    async def create(self, owner_id: int, data: TaskCreate) -> Task:
        if data.status in TaskStatus.closed():
            raise BusinessRuleError("New tasks must start as 'pending' or 'in_progress'")
        if data.due_date < today_utc():
            raise BusinessRuleError("due_date cannot be in the past")

        task = Task(owner_id=owner_id, **data.model_dump())
        await self.tasks.add(task)
        await self.session.commit()
        logger.info("Task created", extra={"task_id": task.id, "owner_id": owner_id})
        return task

    async def get(self, task_id: int, owner_id: int) -> Task:
        task = await self.tasks.get_for_owner(task_id, owner_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        return task

    async def list(
        self, owner_id: int, filters: TaskFilters, *, page: int, size: int
    ) -> tuple[Sequence[Task], int]:
        return await self.tasks.list_for_owner(
            owner_id, filters, today=today_utc(), page=page, size=size
        )

    async def update(self, task_id: int, owner_id: int, data: TaskUpdate) -> Task:
        task = await self.get(task_id, owner_id)
        values = data.model_dump(exclude_unset=True)
        if not values:
            return task

        start_date = values.get("start_date", task.start_date)
        due_date = values.get("due_date", task.due_date)
        if start_date and start_date > due_date:
            raise BusinessRuleError("start_date must be on or before due_date")
        if "due_date" in values and due_date != task.due_date and due_date < today_utc():
            raise BusinessRuleError("due_date cannot be moved into the past")

        if "status" in values:
            values.update(self._status_change(task, values["status"]))

        await self.tasks.update(task, values)
        await self.session.commit()
        return task

    async def change_status(self, task_id: int, owner_id: int, status: TaskStatus) -> Task:
        task = await self.get(task_id, owner_id)
        values = self._status_change(task, status)
        if values:
            await self.tasks.update(task, values)
            await self.session.commit()
            logger.info("Task status changed", extra={"task_id": task.id, "status": status.value})
        return task

    async def delete(self, task_id: int, owner_id: int) -> None:
        task = await self.get(task_id, owner_id)
        await self.tasks.delete(task)
        await self.session.commit()
        logger.info("Task deleted", extra={"task_id": task_id, "owner_id": owner_id})

    async def timeline(
        self, owner_id: int, from_date: date | None = None, to_date: date | None = None
    ) -> TaskTimeline:
        today = today_utc()
        start = from_date or today
        end = to_date or start + timedelta(days=DEFAULT_TIMELINE_DAYS)
        if start > end:
            raise BusinessRuleError("from_date must be on or before to_date")
        if (end - start).days > MAX_TIMELINE_DAYS:
            raise BusinessRuleError(f"Timeline range cannot exceed {MAX_TIMELINE_DAYS} days")

        upcoming = await self.tasks.list_open_due_between(owner_id, start, end)
        overdue = await self.tasks.list_overdue(owner_id, today)

        grouped: dict[date, list[TaskRead]] = defaultdict(list)
        for task in upcoming:
            grouped[task.due_date].append(TaskRead.model_validate(task))

        return TaskTimeline(
            from_date=start,
            to_date=end,
            overdue=[TaskRead.model_validate(task) for task in overdue],
            days=[
                TimelineDay(due_date=day, count=len(items), tasks=items)
                for day, items in sorted(grouped.items())
            ],
        )

    async def summary(self, owner_id: int) -> TaskSummary:
        counts = await self.tasks.count_for_owner(owner_id, today_utc())
        return TaskSummary(
            total=counts.total,
            pending=counts.pending,
            in_progress=counts.in_progress,
            completed=counts.completed,
            cancelled=counts.cancelled,
            overdue=counts.overdue,
            due_today=counts.due_today,
            due_next_7_days=counts.due_next_7_days,
        )

    @staticmethod
    def _status_change(task: Task, new_status: TaskStatus) -> dict[str, Any]:
        """Validate a status transition and return the column values it implies."""
        if new_status == task.status:
            return {}
        if new_status not in ALLOWED_TRANSITIONS[task.status]:
            raise BusinessRuleError(
                f"Cannot change task status from '{task.status.value}' to '{new_status.value}'"
            )
        completed_at = utcnow() if new_status == TaskStatus.COMPLETED else None
        return {"status": new_status, "completed_at": completed_at}
