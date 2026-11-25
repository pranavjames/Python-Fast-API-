from collections.abc import Sequence

from sqlalchemy import or_, select

from app.models.user import User, UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        # Emails are normalised to lower case on write, so this lookup can use the index.
        stmt = select(User).where(User.email == email.lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        size: int,
        search: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[User], int]:
        stmt = select(User)
        if search:
            stmt = stmt.where(
                or_(
                    User.email.icontains(search, autoescape=True),
                    User.full_name.icontains(search, autoescape=True),
                )
            )
        if role is not None:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        stmt = stmt.order_by(User.id)
        return await self.paginate(stmt, page=page, size=size)
