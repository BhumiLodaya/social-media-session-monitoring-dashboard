from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.auth import AuthAuditEvent, LocalSession, SessionEvent, User
from app.routers.auth import admin_user, current_user
from app.schemas.users import (
    UserActivityItem,
    UserDetail,
    UserListResponse,
    UserStatusUpdate,
    UserSummary,
)
from app.time import utcnow

router = APIRouter(prefix="/users", tags=["users"])


def user_summary(db: Session, user: User) -> UserSummary:
    last_login_at = db.scalar(
        select(func.max(AuthAuditEvent.created_at)).where(
            AuthAuditEvent.user_id == user.id,
            AuthAuditEvent.event_type == "dashboard_login",
            AuthAuditEvent.success.is_(True),
        )
    )
    last_logout_at = db.scalar(
        select(func.max(AuthAuditEvent.created_at)).where(
            AuthAuditEvent.user_id == user.id,
            AuthAuditEvent.event_type.in_(("dashboard_logout", "dashboard_session_revoked")),
            AuthAuditEvent.success.is_(True),
        )
    )
    has_active_session = db.scalar(
        select(LocalSession.id)
        .where(
            LocalSession.user_id == user.id,
            LocalSession.revoked_at.is_(None),
            LocalSession.expires_at > utcnow(),
        )
        .limit(1)
    ) is not None
    return UserSummary(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        role=user.role,
        is_demo=user.is_demo,
        created_at=user.created_at,
        last_login_at=last_login_at,
        last_logout_at=last_logout_at,
        session_status="Online" if user.is_active and has_active_session else "Offline",
    )


@router.get("", response_model=UserListResponse)
def list_users(
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> UserListResponse:
    query = select(User)
    if user.role != "admin":
        query = query.where(User.id == user.id)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            User.username.ilike(pattern) | User.email.ilike(pattern)
        )
    users = list(db.scalars(query.order_by(User.username.asc())).all())
    total = len(users)
    start = (page - 1) * page_size
    items = [
        user_summary(db, item)
        for item in users[start:start + page_size]
    ]
    return UserListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{user_id}/details", response_model=UserDetail)
def get_user(
    user_id: int,
    current: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> UserDetail:
    if current.role != "admin" and user_id != current.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    sessions = list(
        db.scalars(select(LocalSession).where(LocalSession.user_id == target.id)).all()
    )
    activity = [
        UserActivityItem(
            id=f"auth-{event.id}",
            occurred_at=event.created_at,
            event_type=(
                "dashboard_login_failed"
                if event.event_type == "dashboard_login" and not event.success
                else event.event_type
            ),
            label=event.account_label,
            source=event.source,
            status="confirmed" if event.confidence == "confirmed" else "unknown",
        )
        for event in db.scalars(
            select(AuthAuditEvent)
            .where(AuthAuditEvent.user_id == target.id)
            .order_by(AuthAuditEvent.created_at.desc())
            .limit(100)
        ).all()
    ]
    activity.extend(
        UserActivityItem(
            id=f"session-{event.id}",
            occurred_at=event.created_at,
            event_type=f"session_{event.event_type}",
            label=target.username,
            source="application",
            status="confirmed",
        )
        for event in db.scalars(
            select(SessionEvent)
            .where(SessionEvent.user_id == target.id)
            .order_by(SessionEvent.created_at.desc())
            .limit(100)
        ).all()
    )
    activity.sort(key=lambda item: item.occurred_at, reverse=True)
    summary = user_summary(db, target)
    return UserDetail(
        **summary.model_dump(),
        session_count=len(sessions),
        active_session_count=sum(1 for session in sessions if session.status == "active"),
        recent_activity=activity[:100],
    )


@router.patch("/{user_id}/status", response_model=UserSummary)
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    current: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> UserSummary:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == current.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrators cannot deactivate their own account",
        )
    if target.is_active == payload.is_active:
        return user_summary(db, target)
    if not payload.is_active and target.role == "admin":
        active_admins = db.scalar(
            select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
        ) or 0
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last active administrator cannot be deactivated",
            )

    now = utcnow()
    target.is_active = payload.is_active
    event_type = "account_activated" if payload.is_active else "account_deactivated"
    db.add(AuthAuditEvent(
        user_id=target.id,
        account_label=target.username,
        event_type=event_type,
        success=True,
        source="admin",
        confidence="confirmed",
        is_demo=target.is_demo,
        created_at=now,
    ))
    if not payload.is_active:
        active_sessions = db.scalars(
            select(LocalSession).where(
                LocalSession.user_id == target.id,
                LocalSession.revoked_at.is_(None),
                LocalSession.expires_at > now,
            )
        ).all()
        for session in active_sessions:
            session.revoked_at = now
            db.add(SessionEvent(
                session_id=session.id,
                user_id=target.id,
                event_type="revoked",
                created_at=now,
            ))
            db.add(AuthAuditEvent(
                user_id=target.id,
                account_label=target.username,
                event_type="dashboard_session_revoked",
                success=True,
                source="admin",
                confidence="confirmed",
                is_demo=target.is_demo,
                created_at=now,
            ))
    db.commit()
    db.refresh(target)
    return user_summary(db, target)
