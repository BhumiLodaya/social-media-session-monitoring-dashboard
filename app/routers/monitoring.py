from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.monitoring import ConsentEvent, NetworkObservation, ProviderConnection
from app.routers.auth import current_user
from app.schemas.monitoring import (
    ConsentEventCreate,
    ConsentEventResponse,
    NetworkObservationResponse,
    NetworkStats,
    ProviderConnectionCreate,
    ProviderConnectionResponse,
)
from app.services.network_ingest import ImportErrorDetail, delete_old_observations, import_export
from app.services.providers import MockProvider, get_connection, sync_connection
from app.services.tshark import TsharkUnavailable, capture_metadata
from app.models.auth import User

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.post("/network/import")
def import_network_export(
    content: bytes = Body(...),
    filename: str = Query(..., min_length=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    del user
    try:
        imported, duplicates = import_export(db, content, filename)
    except ImportErrorDetail as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"imported": imported, "duplicates": duplicates}


@router.post("/network/live")
def capture_live_network_metadata(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    del user
    try:
        content = capture_metadata()
        imported, duplicates = import_export(
            db, content, "live.csv", source="live-captured", method="tshark-live"
        )
    except TsharkUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {"imported": imported, "duplicates": duplicates}


@router.get("/network", response_model=list[NetworkObservationResponse])
def list_network_observations(
    start: datetime | None = None,
    end: datetime | None = None,
    protocol: str | None = None,
    source: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[NetworkObservation]:
    del user
    query = select(NetworkObservation)
    if start:
        query = query.where(NetworkObservation.observed_at >= start)
    if end:
        query = query.where(NetworkObservation.observed_at <= end)
    if protocol:
        query = query.where(NetworkObservation.protocol == protocol.lower())
    if source:
        query = query.where(NetworkObservation.observation_source == source)
    return list(db.scalars(query.order_by(NetworkObservation.observed_at.desc()).limit(limit)).all())


@router.get("/network/stats", response_model=NetworkStats)
def network_stats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> NetworkStats:
    del user
    total = db.scalar(select(func.count(NetworkObservation.id))) or 0
    grouped = db.execute(
        select(NetworkObservation.protocol, func.count(NetworkObservation.id))
        .group_by(NetworkObservation.protocol)
    ).all()
    last = db.scalar(select(func.max(NetworkObservation.imported_at)))
    return NetworkStats(total=total, by_protocol=dict(grouped), last_ingestion_at=last)


@router.post("/network/retention")
def run_retention(
    retention_days: int | None = Query(None, ge=1, le=3650),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    del user
    return {"deleted": delete_old_observations(db, retention_days)}


@router.get("/connections", response_model=list[ProviderConnectionResponse])
def list_connections(
    provider: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(ProviderConnection).where(ProviderConnection.user_id == user.id)
    if provider:
        query = query.where(ProviderConnection.provider == provider)
    return list(db.scalars(query).all())


@router.post("/connections", response_model=ProviderConnectionResponse, status_code=201)
def create_connection(
    payload: ProviderConnectionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderConnection:
    if payload.provider != "mock":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Provider is not configured; use an official authorization adapter",
        )
    connection = ProviderConnection(
        user_id=user.id,
        provider=payload.provider,
        external_account_id=payload.external_account_id,
        connection_mode="mock",
        status="pending",
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return sync_connection(db, connection, MockProvider(payload.scenario))


@router.post("/connections/{connection_id}/sync", response_model=ProviderConnectionResponse)
def sync_provider_connection(
    connection_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderConnection:
    connection = get_connection(db, user.id, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if connection.provider != "mock":
        raise HTTPException(status_code=501, detail="Provider adapter is not configured")
    return sync_connection(db, connection, MockProvider())


@router.get("/consent", response_model=list[ConsentEventResponse])
def list_consent_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(
        select(ConsentEvent).where(ConsentEvent.user_id == user.id)
        .order_by(ConsentEvent.occurred_at.desc()).limit(100)
    ).all())


@router.post("/consent", response_model=ConsentEventResponse, status_code=201)
def create_consent_event(
    payload: ConsentEventCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConsentEvent:
    event = ConsentEvent(user_id=user.id, source="first-party-cmp", **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
