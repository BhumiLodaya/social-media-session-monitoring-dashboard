from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.auth import User
from app.models.session_inventory import SessionInventoryRecord
from app.routers.auth import current_user
from app.schemas.session_inventory import (
    SessionInventoryCreate,
    SessionInventoryListResponse,
    SessionInventoryResponse,
    SessionInventoryStats,
)
from app.time import utcnow

router = APIRouter(prefix="/session-inventory", tags=["session inventory"])


def owned_record(db: Session, record_id: int, user: User) -> SessionInventoryRecord:
    record = db.scalar(
        select(SessionInventoryRecord).where(
            SessionInventoryRecord.id == record_id,
            SessionInventoryRecord.user_id == user.id,
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="Session inventory record not found")
    return record


def refresh_status(record: SessionInventoryRecord, now: datetime) -> None:
    record.last_status_check = now
    if record.revoked_at:
        record.status = "revoked"
        record.status_reason = "Revoked by the owning user."
    elif record.expires_at and record.expires_at <= now:
        record.status = "expired"
        record.status_reason = "Configured expiry time has passed."
    elif record.session_type == "synthetic_demo":
        record.status = "active"
        record.status_reason = "Synthetic demonstration record; not platform authentication."
    else:
        record.status = "unknown"
        record.status_reason = (
            "Browser process and platform authentication are not verified by this application."
        )


@router.post("", response_model=SessionInventoryResponse, status_code=status.HTTP_201_CREATED)
def create_record(
    payload: SessionInventoryCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SessionInventoryRecord:
    if payload.session_type == "synthetic_demo" and payload.platform != "demo":
        raise HTTPException(
            status_code=422,
            detail="Synthetic demonstration records must use platform=demo",
        )
    if payload.session_type == "controlled_browser" and payload.platform == "demo":
        raise HTTPException(
            status_code=422,
            detail="Controlled browser records must use a supported platform label",
        )
    now = utcnow()
    expires_at = payload.expires_at
    if expires_at and expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=None)
    record = SessionInventoryRecord(
        user_id=user.id,
        platform=payload.platform,
        session_type=payload.session_type,
        expires_at=expires_at,
        created_at=now,
        last_status_check=now,
        status="unknown",
        status_reason="",
        browser_process_status="unknown",
        authentication_status="unverified",
    )
    refresh_status(record, now)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=SessionInventoryListResponse)
def list_records(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SessionInventoryListResponse:
    records = list(
        db.scalars(
            select(SessionInventoryRecord)
            .where(SessionInventoryRecord.user_id == user.id)
            .order_by(SessionInventoryRecord.created_at.desc())
        ).all()
    )
    return SessionInventoryListResponse(items=records, total=len(records))


@router.get("/stats", response_model=SessionInventoryStats)
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)) -> SessionInventoryStats:
    records = list(
        db.scalars(select(SessionInventoryRecord).where(SessionInventoryRecord.user_id == user.id)).all()
    )
    return SessionInventoryStats(
        total=len(records),
        by_status={key: sum(record.status == key for record in records)
                   for key in ("active", "inactive", "expired", "revoked", "unknown")},
        by_platform={platform: sum(record.platform == platform for record in records)
                     for platform in ("instagram", "facebook", "demo")},
    )


@router.post("/{record_id}/refresh", response_model=SessionInventoryResponse)
def refresh_record(
    record_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SessionInventoryRecord:
    record = owned_record(db, record_id, user)
    refresh_status(record, utcnow())
    db.commit()
    db.refresh(record)
    return record


@router.post("/{record_id}/revoke", response_model=SessionInventoryResponse)
def revoke_record(
    record_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SessionInventoryRecord:
    record = owned_record(db, record_id, user)
    if not record.revoked_at:
        record.revoked_at = utcnow()
    refresh_status(record, utcnow())
    db.commit()
    db.refresh(record)
    return record
