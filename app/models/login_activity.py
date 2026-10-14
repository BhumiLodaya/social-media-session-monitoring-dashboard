from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.time import utcnow


class DemoActivityEvent(Base):
    __tablename__ = "demo_activity_events"
    __table_args__ = (UniqueConstraint("user_id", "demo_key", name="uq_demo_activity_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    demo_key: Mapped[str] = mapped_column(String(80))
    account_label: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    device_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
