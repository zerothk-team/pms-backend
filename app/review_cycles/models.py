import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.review_cycles.enums import CycleStatus, CycleType


class ReviewCycle(Base):
    __tablename__ = "review_cycles"

    __table_args__ = (
        Index("ix_review_cycle_org_status", "organisation_id", "status"),
        Index("ix_review_cycle_dates", "start_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cycle_type: Mapped[CycleType] = mapped_column(
        SAEnum(CycleType, name="cycletype"), nullable=False
    )
    status: Mapped[CycleStatus] = mapped_column(
        SAEnum(CycleStatus, name="cyclestatus"),
        nullable=False,
        default=CycleStatus.DRAFT,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_setting_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_entry_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scoring_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # Relationships
    organisation: Mapped["Organisation"] = relationship(  # type: ignore[name-defined]
        "Organisation", foreign_keys=[organisation_id]
    )
    created_by: Mapped[Optional["User"]] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[created_by_id]
    )
    targets: Mapped[list["KPITarget"]] = relationship(  # type: ignore[name-defined]
        "KPITarget", back_populates="review_cycle", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ReviewCycle id={self.id} name={self.name!r} status={self.status}>"
