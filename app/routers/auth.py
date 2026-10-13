from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.auth import SessionEvent, User
from app.schemas.auth import LoginRequest, UserResponse
from app.services.auth import authenticate, create_session, get_valid_session
from app.time import utcnow

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


def current_user(
    session_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    session = get_valid_session(db, session_token)
    user = db.get(User, session.user_id) if session else None
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    user = authenticate(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    response.set_cookie(
        "session_token", create_session(db, user),
        max_age=settings.session_max_age_seconds, httponly=True,
        samesite="lax", secure=settings.session_cookie_secure,
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    session = get_valid_session(db, session_token)
    if session:
        session.revoked_at = utcnow()
        db.add(SessionEvent(session_id=session.id, user_id=session.user_id, event_type="revoked"))
        db.commit()
    response.delete_cookie("session_token")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)) -> User:
    return user
