from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.auth import AuthAuditEvent, SessionEvent, User
from app.schemas.auth import LoginRequest, RegistrationRequest, UserResponse
from app.services.auth import authenticate, create_session, get_valid_session
from app.services.auth import pwd_context
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


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    user = authenticate(db, payload.username, payload.password)
    if not user:
        known_user = db.scalar(
            select(User).where(func.lower(User.username) == payload.username.strip().lower())
        )
        db.add(AuthAuditEvent(
            user_id=known_user.id if known_user else None,
            account_label=known_user.username if known_user else "Unknown account",
            event_type="dashboard_login",
            success=False,
            source="application",
            confidence="confirmed",
            is_demo=known_user.is_demo if known_user else False,
        ))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    db.add(AuthAuditEvent(
        user_id=user.id,
        account_label=user.username,
        event_type="dashboard_login",
        success=True,
        source="application",
        confidence="confirmed",
        is_demo=user.is_demo,
    ))
    db.commit()
    response.set_cookie(
        "session_token", create_session(db, user),
        max_age=settings.session_max_age_seconds, httponly=True,
        samesite="lax", secure=settings.session_cookie_secure,
    )
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, db: Session = Depends(get_db)) -> User:
    if db.scalar(select(User.id).where(User.username.ilike(payload.username))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username is already registered")
    if db.scalar(select(User.id).where(User.email.ilike(payload.email))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=pwd_context.hash(payload.password),
        is_active=True,
        created_at=utcnow(),
    )
    db.add(user)
    try:
        db.flush()
        db.add(AuthAuditEvent(
            user_id=user.id,
            account_label=user.username,
            event_type="account_registered",
            success=True,
            source="application",
            confidence="confirmed",
            is_demo=user.is_demo,
        ))
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that username or email already exists",
        ) from error
    db.refresh(user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    session = get_valid_session(db, session_token)
    if session:
        user = db.get(User, session.user_id)
        session.revoked_at = utcnow()
        db.add(SessionEvent(session_id=session.id, user_id=session.user_id, event_type="revoked"))
        if user:
            db.add(AuthAuditEvent(
                user_id=user.id,
                account_label=user.username,
                event_type="dashboard_logout",
                success=True,
                source="application",
                confidence="confirmed",
                is_demo=user.is_demo,
            ))
        db.commit()
    response.delete_cookie("session_token")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)) -> User:
    return user
