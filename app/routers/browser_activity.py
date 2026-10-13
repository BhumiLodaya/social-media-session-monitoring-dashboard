from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models.auth import User
from app.models.browser_activity import BrowserActivityEvent, BrowserExtensionDevice
from app.routers.auth import current_user
from app.schemas.browser_activity import (
    BrowserActivityEventCreate,
    BrowserActivityEventResponse,
    BrowserActivityStats,
    BrowserActivityStatusResponse,
    BrowserActivityPlatformStatus,
    BrowserExtensionDeviceResponse,
    BrowserExtensionPairingExchange,
    BrowserExtensionPairingStartResponse,
    BrowserExtensionTokenResponse,
)
from app.services.browser_activity import (
    create_activity_event,
    create_pairing_code,
    exchange_pairing_code,
    get_active_extension_device,
)
from app.time import utcnow

router = APIRouter(tags=["browser activity"])
bearer = HTTPBearer(auto_error=False)
MAX_EVENT_REQUEST_BYTES = 16 * 1024


def extension_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> BrowserExtensionDevice:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Extension authorization required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_active_extension_device(db, credentials.credentials)


@router.post(
    "/browser-extension/pairing/start",
    response_model=BrowserExtensionPairingStartResponse,
)
def start_pairing(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> BrowserExtensionPairingStartResponse:
    code, pairing = create_pairing_code(db, user)
    return BrowserExtensionPairingStartResponse(
        pairing_code=code,
        expires_at=pairing.expires_at,
    )


@router.post(
    "/browser-extension/pairing/exchange",
    response_model=BrowserExtensionTokenResponse,
)
def exchange_pairing(
    payload: BrowserExtensionPairingExchange,
    db: Session = Depends(get_db),
) -> BrowserExtensionTokenResponse:
    token, device = exchange_pairing_code(
        db, payload.pairing_code, payload.installation_label
    )
    return BrowserExtensionTokenResponse(device=device, extension_token=token)


@router.get(
    "/browser-extension/devices",
    response_model=list[BrowserExtensionDeviceResponse],
)
def list_devices(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[BrowserExtensionDevice]:
    return list(
        db.scalars(
            select(BrowserExtensionDevice)
            .where(BrowserExtensionDevice.user_id == user.id)
            .order_by(BrowserExtensionDevice.created_at.desc())
        ).all()
    )


@router.post("/browser-extension/devices/{device_id}/revoke", status_code=204)
def revoke_device(
    device_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    device = db.scalar(
        select(BrowserExtensionDevice).where(
            BrowserExtensionDevice.id == device_id,
            BrowserExtensionDevice.user_id == user.id,
        )
    )
    if not device:
        raise HTTPException(status_code=404, detail="Extension device not found")
    if not device.revoked_at:
        from app.time import utcnow

        device.revoked_at = utcnow()
        db.commit()


@router.post(
    "/browser-activity/events",
    response_model=BrowserActivityEventResponse,
)
def ingest_event(
    payload: BrowserActivityEventCreate,
    request: Request,
    device: BrowserExtensionDevice = Depends(extension_device),
    db: Session = Depends(get_db),
) -> BrowserActivityEvent:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > MAX_EVENT_REQUEST_BYTES
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if too_large:
            raise HTTPException(status_code=413, detail="Request body is too large")
    return create_activity_event(db, device, payload)


@router.get(
    "/browser-activity/events",
    response_model=list[BrowserActivityEventResponse],
)
def list_events(
    start: datetime | None = None,
    end: datetime | None = None,
    domain: str | None = None,
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[BrowserActivityEvent]:
    query = select(BrowserActivityEvent).where(BrowserActivityEvent.user_id == user.id)
    if start:
        query = query.where(BrowserActivityEvent.occurred_at >= start.replace(tzinfo=None))
    if end:
        query = query.where(BrowserActivityEvent.occurred_at <= end.replace(tzinfo=None))
    if domain:
        query = query.where(BrowserActivityEvent.domain == domain.lower().rstrip("."))
    if event_type:
        query = query.where(BrowserActivityEvent.event_type == event_type)
    return list(db.scalars(query.order_by(BrowserActivityEvent.occurred_at.desc()).limit(limit)).all())


@router.get("/browser-activity/stats", response_model=BrowserActivityStats)
def activity_stats(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> BrowserActivityStats:
    base = select(BrowserActivityEvent).where(BrowserActivityEvent.user_id == user.id)
    events = list(db.scalars(base).all())
    by_domain = {}
    by_event_type = {}
    for event in events:
        by_domain[event.domain] = by_domain.get(event.domain, 0) + 1
        by_event_type[event.event_type] = by_event_type.get(event.event_type, 0) + 1
    return BrowserActivityStats(
        total=len(events),
        by_domain=by_domain,
        by_event_type=by_event_type,
        duration_seconds=sum(event.duration_seconds or 0 for event in events),
    )


@router.get("/browser-activity/status", response_model=BrowserActivityStatusResponse)
def activity_status(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> BrowserActivityStatusResponse:
    threshold_seconds = get_settings().browser_activity_inactivity_threshold_seconds
    now = utcnow()
    cutoff = now - timedelta(seconds=threshold_seconds)
    devices = list(
        db.scalars(
            select(BrowserExtensionDevice).where(
                BrowserExtensionDevice.user_id == user.id
            )
        ).all()
    )
    monitoring_is_functioning = any(
        not device.revoked_at
        and (device.expires_at is None or device.expires_at > now)
        and device.last_seen_at is not None
        and device.last_seen_at >= cutoff
        for device in devices
    )
    items = []
    for platform in ("facebook", "instagram"):
        latest = db.scalar(
            select(BrowserActivityEvent)
            .where(
                BrowserActivityEvent.user_id == user.id,
                BrowserActivityEvent.domain == f"{platform}.com",
            )
            .order_by(BrowserActivityEvent.occurred_at.desc())
            .limit(1)
        )
        last_activity_at = latest.occurred_at if latest else None
        if latest and cutoff <= latest.occurred_at <= now:
            current_status = "recently_active"
            explanation = (
                "A consented browser activity event was observed within the "
                f"last {threshold_seconds // 60} minutes."
            )
        elif monitoring_is_functioning:
            current_status = "inactive"
            explanation = (
                "Extension monitoring is currently functioning, but no "
                f"{platform.capitalize()} activity was observed within the "
                f"last {threshold_seconds // 60} minutes."
            )
        else:
            current_status = "unknown"
            explanation = (
                "Monitoring is not known to be functioning; the extension "
                "may be disconnected, paused, expired, or revoked."
            )
        items.append(
            BrowserActivityPlatformStatus(
                platform=platform,
                status=current_status,
                last_activity_at=last_activity_at,
                explanation=explanation,
            )
        )
    return BrowserActivityStatusResponse(
        inactivity_threshold_seconds=threshold_seconds,
        items=items,
    )
