from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.time import utcnow


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    redirect_uri: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SocialParticipant(Base):
    __tablename__ = "social_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_connections.id"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="unconnected")
    consent_status: Mapped[str] = mapped_column(String(20), default="pending")
    consent_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    consent_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    participation_status: Mapped[str] = mapped_column(String(20), default="paused")
    connection_health: Mapped[str] = mapped_column(String(20), default="unknown")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ParticipantAuditEvent(Base):
    __tablename__ = "participant_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("social_participants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PostMetric(Base):
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_connection_id: Mapped[int] = mapped_column(ForeignKey("provider_connections.id"), index=True)
    external_post_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    likes: Mapped[int | None] = mapped_column(nullable=True)
    comments: Mapped[int | None] = mapped_column(nullable=True)
    reach: Mapped[int | None] = mapped_column(nullable=True)
    impressions: Mapped[int | None] = mapped_column(nullable=True)
    shares: Mapped[int | None] = mapped_column(nullable=True, default=None)
    saves: Mapped[int | None] = mapped_column(nullable=True, default=None)
    source: Mapped[str] = mapped_column(String(20), default="live")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
