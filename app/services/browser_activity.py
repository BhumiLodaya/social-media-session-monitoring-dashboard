import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.auth import User
from app.models.browser_activity import (
    BrowserActivityEvent,
    BrowserExtensionDevice,
    BrowserExtensionPairingCode,
)
from app.schemas.browser_activity import BrowserActivityEventCreate
from app.time import utcnow


def hash_extension_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_pairing_code(db: Session, user: User) -> tuple[str, BrowserExtensionPairingCode]:
    now = utcnow()
    raw_code = secrets.token_urlsafe(32)
    pairing = BrowserExtensionPairingCode(
        user_id=user.id,
        code_hash=hash_extension_secret(raw_code),
        created_at=now,
        expires_at=now + timedelta(seconds=get_settings().browser_extension_pairing_ttl_seconds),
    )
    db.add(pairing)
    db.commit()
    db.refresh(pairing)
    return raw_code, pairing


def exchange_pairing_code(
    db: Session,
    raw_code: str,
    installation_label: str,
) -> tuple[str, BrowserExtensionDevice]:
    pairing = db.scalar(
        select(BrowserExtensionPairingCode).where(
            BrowserExtensionPairingCode.code_hash == hash_extension_secret(raw_code)
        )
    )
    now = utcnow()
    if not pairing or pairing.used_at or pairing.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired pairing code")

    claimed = db.execute(
        update(BrowserExtensionPairingCode)
        .where(
            BrowserExtensionPairingCode.id == pairing.id,
            BrowserExtensionPairingCode.used_at.is_(None),
            BrowserExtensionPairingCode.expires_at > now,
        )
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired pairing code")

    extension_token = secrets.token_urlsafe(48)
    device = BrowserExtensionDevice(
        user_id=pairing.user_id,
        installation_label=installation_label,
        token_hash=hash_extension_secret(extension_token),
        created_at=now,
        expires_at=now + timedelta(seconds=get_settings().browser_extension_token_ttl_seconds),
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return extension_token, device


def get_active_extension_device(db: Session, token: str) -> BrowserExtensionDevice:
    device = db.scalar(
        select(BrowserExtensionDevice).where(
            BrowserExtensionDevice.token_hash == hash_extension_secret(token)
        )
    )
    now = utcnow()
    if (
        not device
        or device.revoked_at
        or (device.expires_at is not None and device.expires_at <= now)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Extension authorization required")
    device.last_seen_at = now
    db.commit()
    return device


def create_activity_event(
    db: Session,
    device: BrowserExtensionDevice,
    payload: BrowserActivityEventCreate,
) -> BrowserActivityEvent:
    existing = db.scalar(
        select(BrowserActivityEvent).where(
            BrowserActivityEvent.extension_device_id == device.id,
            BrowserActivityEvent.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return existing
    event = BrowserActivityEvent(
        user_id=device.user_id,
        extension_device_id=device.id,
        event_type=payload.event_type,
        occurred_at=payload.occurred_at.replace(tzinfo=None),
        domain=payload.domain,
        duration_seconds=payload.duration_seconds,
        metadata_json=payload.metadata,
        consent_version=payload.consent_version,
        idempotency_key=payload.idempotency_key,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(BrowserActivityEvent).where(
                BrowserActivityEvent.extension_device_id == device.id,
                BrowserActivityEvent.idempotency_key == payload.idempotency_key,
            )
        )
        if existing:
            return existing
        raise
    db.refresh(event)
    return event
