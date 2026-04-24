import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SizeBand(str, enum.Enum):
    micro = "1-10"
    small = "11-50"
    medium = "51-200"
    large = "201-500"
    enterprise = "500+"


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_band: Mapped[Optional[SizeBand]] = mapped_column(SAEnum(SizeBand), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    # Relationships
    users: Mapped[list["User"]] = relationship(  # type: ignore[name-defined]
        "User", back_populates="organisation"
    )

    def __repr__(self) -> str:
        return f"<Organisation id={self.id} name={self.name}>"
