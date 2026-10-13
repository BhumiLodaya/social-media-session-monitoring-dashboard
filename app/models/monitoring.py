from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.time import utcnow


class NetworkObservation(Base):
    __tablename__ = "network_observations"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_network_observation_dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    protocol: Mapped[str] = mapped_column(String(40), index=True)
    source_category: Mapped[str] = mapped_column(String(80), default="unknown")
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    packet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observation_source: Mapped[str] = mapped_column(String(40), default="imported")
    observation_method: Mapped[str] = mapped_column(String(80), default="tshark-export")
    confidence: Mapped[str] = mapped_column(String(20), default="metadata")
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "external_account_id", name="uq_provider_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    external_account_id: Mapped[str] = mapped_column(String(255))
    connection_mode: Mapped[str] = mapped_column(String(20), default="mock")
    authorization_status: Mapped[str] = mapped_column(String(30), default="not_authorized")
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConsentEvent(Base):
    __tablename__ = "consent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    website: Mapped[str] = mapped_column(String(255))
    choice: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(80), default="first-party-cmp")
