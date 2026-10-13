import hashlib
import secrets
from datetime import datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.auth import LocalSession, SessionEvent, User
from app.time import utcnow

pwd_context = PasswordHash.recommended()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or not pwd_context.verify(password, user.password_hash):
        return None
    return user


def create_session(db: Session, user: User, max_age_seconds: int | None = None) -> str:
    token = secrets.token_urlsafe(32)
    session = LocalSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        last_activity_at=utcnow(),
        expires_at=utcnow() + timedelta(
            seconds=max_age_seconds
            if max_age_seconds is not None
            else get_settings().session_max_age_seconds
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="created"))
    db.commit()
    return token


def get_valid_session(db: Session, token: str | None) -> LocalSession | None:
    if not token:
        return None
    session = db.scalar(select(LocalSession).where(LocalSession.token_hash == hash_session_token(token)))
    if not session or session.revoked_at or session.expires_at <= utcnow():
        return None
    session.last_activity_at = utcnow()
    db.commit()
    return session
