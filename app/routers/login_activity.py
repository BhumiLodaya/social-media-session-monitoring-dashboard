from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.auth import AuthAuditEvent, LocalSession, SessionEvent, User
from app.models.browser_activity import BrowserActivityEvent
from app.models.dashboard_activity import DashboardPanelEvent
from app.models.login_activity import DemoActivityEvent
from app.models.monitoring import ProviderConnection
from app.routers.auth import current_user
from app.schemas.login_activity import (
    DemoActivityResponse,
    LoginActivityItem,
    LoginActivityResponse,
    LoginActivityStats,
    PanelOpenRequest,
    PanelOpenResponse,
    PanelUsageItem,
    PanelUsageResponse,
)
from app.time import utcnow

router = APIRouter(prefix="/login-activity", tags=["login activity"])


def browser_item(event: BrowserActivityEvent, user: User) -> LoginActivityItem:
    return LoginActivityItem(
        id=f"browser-{event.id}",
        occurred_at=event.occurred_at,
        account_label=user.username,
        platform=event.domain.split(".")[0].capitalize(),
        event_type="navigation_observed",
        source=event.source,
        status="observed",
        confidence="unknown",
        device_label=None,
        is_demo=False,
        metadata=event.metadata_json,
    )


def session_item(session: SessionEvent, event_type: str, user: User) -> LoginActivityItem:
    return LoginActivityItem(
        id=f"session-{session.id}",
        occurred_at=session.created_at,
        account_label=user.username,
        platform="Dashboard",
        event_type=f"session_{event_type}",
        source="application",
        status="confirmed",
        confidence="confirmed",
        device_label=None,
        is_demo=user.is_demo,
    )


def oauth_connection_item(connection: ProviderConnection) -> LoginActivityItem:
    return LoginActivityItem(
        id=f"oauth-{connection.id}",
        occurred_at=connection.created_at,
        account_label=connection.external_account_id,
        platform=connection.provider or "Unknown",
        event_type="social_connection",
        source="application",
        status="confirmed" if connection.authorization_status == "authorized" else "unknown",
        confidence="confirmed" if connection.authorization_status == "authorized" else "unknown",
        device_label=None,
        is_demo=connection.connection_mode == "demo",
    )


def oauth_disconnect_item(connection: ProviderConnection) -> LoginActivityItem:
    return LoginActivityItem(
        id=f"oauth-disconnect-{connection.id}",
        occurred_at=connection.updated_at,
        account_label=connection.external_account_id,
        platform=connection.provider or "Unknown",
        event_type="social_disconnection",
        source="application",
        status="confirmed",
        confidence="confirmed",
        device_label=None,
        is_demo=connection.connection_mode == "demo",
    )


@router.get("/events", response_model=LoginActivityResponse)
def list_activity(
    platform: str | None = Query(None, max_length=40),
    event_type: str | None = Query(None, max_length=50),
    source: str | None = Query(None, max_length=40),
    activity_status: str | None = Query(None, alias="status", pattern="^(confirmed|observed|unknown)$"),
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> LoginActivityResponse:
    auth_events = list(db.scalars(select(AuthAuditEvent).where(AuthAuditEvent.user_id == user.id)).all())
    session_events = list(db.scalars(select(SessionEvent).where(SessionEvent.user_id == user.id)).all())
    browser_events = list(db.scalars(select(BrowserActivityEvent).where(
        BrowserActivityEvent.user_id == user.id
    )).all())
    demo_events = list(db.scalars(select(DemoActivityEvent).where(
        DemoActivityEvent.user_id == user.id,
        DemoActivityEvent.is_demo.is_(True),
    )).all())
    panel_events = list(db.scalars(select(DashboardPanelEvent).where(
        DashboardPanelEvent.user_id == user.id
    )).all())
    # Provider connection events
    connections = list(db.scalars(select(ProviderConnection).where(ProviderConnection.user_id == user.id)).all())

    items = [
        LoginActivityItem(
            id=f"auth-{event.id}", occurred_at=event.created_at, account_label=event.account_label,
            platform="Dashboard",
            event_type=(
                "dashboard_login_failed"
                if event.event_type == "dashboard_login" and not event.success
                else event.event_type
            ),
            source=event.source,
            status="confirmed", confidence=event.confidence, device_label=None, is_demo=event.is_demo,
        )
        for event in auth_events
    ] + [
        session_item(session, session.event_type, user)
        for session in session_events
    ] + [
        oauth_connection_item(conn) for conn in connections if conn.authorization_status == "authorized"
    ] + [
        oauth_disconnect_item(conn) for conn in connections if conn.authorization_status in ["revoked", "expired", "not_authorized"]
    ] + [browser_item(event, user) for event in browser_events] + [
        LoginActivityItem(
            id=f"demo-{event.id}", occurred_at=event.occurred_at, account_label=event.account_label,
            platform=event.platform, event_type=event.event_type, source=event.source,
            status=event.status, confidence=event.confidence, device_label=event.device_label, is_demo=True,
        )
        for event in demo_events
    ] + [
        LoginActivityItem(
            id=f"panel-{event.id}",
            occurred_at=event.occurred_at,
            account_label=user.username,
            platform="Dashboard",
            event_type="panel_opened",
            source="application",
            status="confirmed",
            confidence="confirmed",
            device_label=event.panel_id,
            is_demo=False,
        )
        for event in panel_events
    ]
    if start:
        items = [item for item in items if item.occurred_at >= start.replace(tzinfo=None)]
    if end:
        items = [item for item in items if item.occurred_at <= end.replace(tzinfo=None)]
    if platform:
        items = [item for item in items if item.platform.lower() == platform.lower()]
    if event_type:
        items = [item for item in items if item.event_type == event_type]
    if source:
        items = [item for item in items if item.source == source]
    if activity_status:
        items = [item for item in items if item.status == activity_status]
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    total = len(items)
    offset = (page - 1) * page_size
    return LoginActivityResponse(items=items[offset:offset + page_size], total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=LoginActivityStats)
def activity_stats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> LoginActivityStats:
    events = list(db.scalars(select(AuthAuditEvent).where(AuthAuditEvent.user_id == user.id)).all())
    browser_count = db.query(BrowserActivityEvent).filter(BrowserActivityEvent.user_id == user.id).count()
    connections = list(db.scalars(select(ProviderConnection).where(ProviderConnection.user_id == user.id)).all())
    return LoginActivityStats(
        recent_observed_events=browser_count,
        successful_dashboard_logins=sum(
            event.event_type == "dashboard_login" and event.success for event in events
        ),
        failed_dashboard_logins=sum(
            event.event_type == "dashboard_login" and not event.success for event in events
        ),
        connected_social_accounts=sum(connection.authorization_status == "authorized" for connection in connections),
        accounts_requiring_reconnection=sum(connection.authorization_status != "authorized" for connection in connections),
    )


ALLOWED_PANEL_IDS = frozenset({
    "overview", "users", "user-detail", "login-activity", "sessions", "monitoring", "panels",
    "connected-accounts", "organic-ids", "diagnosis",
})


@router.post("/panels", response_model=PanelOpenResponse, status_code=201)
def record_panel_open(
    payload: PanelOpenRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DashboardPanelEvent:
    if payload.panel_id not in ALLOWED_PANEL_IDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown panel identifier")
    event = DashboardPanelEvent(user_id=user.id, panel_id=payload.panel_id, occurred_at=utcnow())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/panels", response_model=PanelUsageResponse)
def list_panel_usage(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PanelUsageResponse:
    query = (
        select(DashboardPanelEvent, User.username)
        .join(User, User.id == DashboardPanelEvent.user_id)
        .where(DashboardPanelEvent.user_id == user.id)
        .order_by(DashboardPanelEvent.occurred_at.desc())
    )
    rows = list(db.execute(query).all())
    total = len(rows)
    offset = (page - 1) * page_size
    page_rows = rows[offset:offset + page_size]
    items = [
        PanelUsageItem(id=event.id, panel_id=event.panel_id, occurred_at=event.occurred_at, username=username)
        for event, username in page_rows
    ]
    return PanelUsageResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/demo", response_model=DemoActivityResponse)
def create_demo_activity(user: User = Depends(current_user), db: Session = Depends(get_db)) -> DemoActivityResponse:
    records = [
        ("dashboard-success", "Demo operator", "Dashboard", "dashboard_login", "confirmed", "confirmed"),
        ("social-navigation", "Synthetic creator", "Instagram", "navigation_observed", "observed", "unknown"),
        ("social-state-unknown", "Synthetic creator", "Facebook", "status_unknown", "unknown", "unknown"),
    ]
    created = 0
    for key, label, platform, event_type, status_value, confidence in records:
        if db.scalar(select(DemoActivityEvent).where(
            DemoActivityEvent.user_id == user.id, DemoActivityEvent.demo_key == key
        )):
            continue
        db.add(DemoActivityEvent(
            user_id=user.id, demo_key=key, account_label=label, platform=platform,
            event_type=event_type, status=status_value, confidence=confidence,
            source="synthetic-demo", device_label="Demo browser", occurred_at=utcnow(),
        ))
        created += 1
    db.commit()
    return DemoActivityResponse(created=created, message="Synthetic login activity is ready")
