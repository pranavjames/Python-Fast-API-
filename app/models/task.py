from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Date, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    MYSQL_TABLE_ARGS,
    Base,
    BigIntPK,
    IdMixin,
    TimestampMixin,
    UTCDateTime,
)


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @classmethod
    def closed(cls) -> frozenset["TaskStatus"]:
        return frozenset({cls.COMPLETED, cls.CANCELLED})


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


def today_utc() -> date:
    return datetime.now(UTC).date()


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner_id_due_date", "owner_id", "due_date"),
        Index("ix_tasks_owner_id_status", "owner_id", "status"),
        MYSQL_TABLE_ARGS,
    )

    owner_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            values_callable=lambda e: [m.value for m in e],
            validate_strings=True,
        ),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(
            TaskPriority,
            name="task_priority",
            values_callable=lambda e: [m.value for m in e],
            validate_strings=True,
        ),
        default=TaskPriority.MEDIUM,
        nullable=False,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    @property
    def is_closed(self) -> bool:
        return self.status in TaskStatus.closed()

    @property
    def is_overdue(self) -> bool:
        return not self.is_closed and self.due_date < today_utc()

    @property
    def days_remaining(self) -> int | None:
        """Days until the due date (negative when overdue); None once the task is closed."""
        if self.is_closed:
            return None
        return (self.due_date - today_utc()).days

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} due={self.due_date}>"
