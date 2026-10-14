from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.auth import AuthAuditEvent, LocalSession, SessionEvent, User
from app.routers.auth import current_user
from app.schemas.session import (
    SessionEventListResponse,
    SessionListResponse,
    SessionResponse,
    SessionStats,
)
from app.time import utcnow

router = APIRouter(prefix="/sessions", tags=["sessions"])


def owned_session(db: Session, session_id: int, user: User) -> LocalSession:
    session = db.scalar(select(LocalSession).where(
        LocalSession.id == session_id, LocalSession.user_id == user.id
    ))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.get("", response_model=SessionListResponse)
def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session_status: str | None = Query(None, alias="status", pattern="^(active|expired|revoked)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SessionListResponse:
    query = select(LocalSession).where(LocalSession.user_id == user.id)
    sessions = list(db.scalars(query.order_by(LocalSession.created_at.desc())).all())
    if session_status:
        sessions = [item for item in sessions if item.status == session_status]
    total = len(sessions)
    start = (page - 1) * page_size
    return SessionListResponse(items=sessions[start:start + page_size], total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=SessionStats)
def session_stats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> SessionStats:
    sessions = list(db.scalars(select(LocalSession).where(LocalSession.user_id == user.id)).all())
    counts = {key: sum(item.status == key for item in sessions) for key in ("active", "expired", "revoked")}
    return SessionStats(total=len(sessions), **counts)


@router.get("/events", response_model=SessionEventListResponse)
def session_events(
    event_type: str | None = Query(None, min_length=1, max_length=50),
    start: datetime | None = None,
    end: datetime | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> SessionEventListResponse:
    query = select(SessionEvent).where(SessionEvent.user_id == user.id)
    if event_type:
        query = query.where(SessionEvent.event_type == event_type)
    if start:
        query = query.where(SessionEvent.created_at >= start)
    if end:
        query = query.where(SessionEvent.created_at <= end)
    events = db.scalars(query.order_by(SessionEvent.created_at.desc()).limit(100)).all()
    return SessionEventListResponse(items=list(events))


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> LocalSession:
    return owned_session(db, session_id, user)


@router.post("/{session_id}/revoke", response_model=SessionResponse)
def revoke_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> LocalSession:
    session = owned_session(db, session_id, user)
    if not session.revoked_at:
        session.revoked_at = utcnow()
        db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="revoked"))
        db.add(AuthAuditEvent(
            user_id=user.id,
            account_label=user.username,
            event_type="dashboard_session_revoked",
            success=True,
            source="application",
            confidence="confirmed",
            is_demo=user.is_demo,
        ))
        db.commit()
        db.refresh(session)
    return session
