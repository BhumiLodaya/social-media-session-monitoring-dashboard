from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.time import utcnow


class SessionInventoryRecord(Base):
    __tablename__ = "session_inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    session_type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_observed_activity: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status_check: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status_reason: Mapped[str] = mapped_column(String(255))
    browser_process_status: Mapped[str] = mapped_column(String(20), default="unknown")
    authentication_status: Mapped[str] = mapped_column(String(30), default="unverified")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
