import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    hr_admin = "hr_admin"
    executive = "executive"
    manager = "manager"
    employee = "employee"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    organisation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organisations.id"), nullable=True
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    organisation: Mapped[Optional["Organisation"]] = relationship(  # type: ignore[name-defined]
        "Organisation", back_populates="users", foreign_keys=[organisation_id]
    )
    manager: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="direct_reports",
        remote_side="User.id",
        foreign_keys="[User.manager_id]",
    )
    direct_reports: Mapped[list["User"]] = relationship(
        "User",
        back_populates="manager",
        foreign_keys="[User.manager_id]",
    )
    # kpis relationship added in Part 2 when KpiModel is defined

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
