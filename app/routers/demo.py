from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.auth import LocalSession, SessionEvent, User
from app.routers.auth import current_user
from app.services.auth import create_session, hash_session_token, pwd_context
from app.time import utcnow

router = APIRouter(prefix="/demo", tags=["local demo"])
DEMO_USERNAME = "demo-alice"
DEMO_PASSWORD = "DemoOnlyPass123!"


class DemoSessionRequest(BaseModel):
    duration_seconds: int = Field(default=30, ge=1, le=3600)


def demo_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user:
        return user
    user = User(username=DEMO_USERNAME, password_hash=pwd_context.hash(DEMO_PASSWORD))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("")
def demo_page() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "templates" / "demo.html")


@router.post("/start")
def start_demo(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    """Sign in as the synthetic account and create its first browser session."""
    user = demo_user(db)
    dashboard_token = create_session(db, user)
    response.set_cookie(
        "session_token",
        dashboard_token,
        max_age=get_settings().session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
    )
    return {"username": user.username, "message": "Synthetic demo started"}


@router.post("/sessions")
def create_demo_session(
    payload: DemoSessionRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if user.username != DEMO_USERNAME:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Synthetic demo account required")
    token = create_session(db, user, payload.duration_seconds)
    session = db.scalar(select(LocalSession).where(LocalSession.token_hash == hash_session_token(token)))
    if not session:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Demo session was not created")
    return {"id": session.id, "status": session.status, "expires_at": session.expires_at}


@router.post("/sessions/{session_id}/expire")
def expire_demo_session(
    session_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if user.username != DEMO_USERNAME:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Synthetic demo account required")
    session = db.scalar(
        select(LocalSession).where(LocalSession.id == session_id, LocalSession.user_id == user.id)
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status == "active":
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="expired"))
        db.commit()
    return {"id": session.id, "status": session.status}
