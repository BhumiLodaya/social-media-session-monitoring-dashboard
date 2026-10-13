import csv
import hashlib
import io
import ipaddress
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.monitoring import NetworkObservation
from app.time import utcnow

SUPPORTED_PROTOCOLS = {
    "tcp", "udp", "http", "https", "dns", "tls", "quic", "icmp", "ssh", "other",
}
# TShark protocol display labels that are equivalent to a supported protocol.
PROTOCOL_ALIASES = {
    "ssl": "tls",
    "tlsv1": "tls",
    "tlsv1.0": "tls",
    "tlsv1.1": "tls",
    "tlsv1.2": "tls",
    "tlsv1.3": "tls",
}


class ImportErrorDetail(ValueError):
    pass


def _value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if record.get(name) not in (None, ""):
            return record[name]
    return None


def _timestamp(value: Any) -> datetime:
    if value in (None, ""):
        raise ImportErrorDetail("timestamp is required")
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ImportErrorDetail("timestamp must be ISO-8601") from exc
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)


def _integer(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ImportErrorDetail(f"{field} must be an integer") from exc
    if result < 0:
        raise ImportErrorDetail(f"{field} must not be negative")
    return result


def _number(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ImportErrorDetail(f"{field} must be a number") from exc
    if result < 0:
        raise ImportErrorDetail(f"{field} must not be negative")
    return result


def _normalize_protocol(value: Any) -> str:
    protocol = str(value).strip().lower() if value not in (None, "") else ""
    if protocol in SUPPORTED_PROTOCOLS:
        return protocol
    return PROTOCOL_ALIASES.get(protocol, "other")


def normalize_record(record: dict[str, Any], source: str = "imported") -> dict[str, Any]:
    protocol = _normalize_protocol(
        _value(record, "protocol", "_ws.col.protocol", "_ws.col.Protocol", "frame.protocols")
    ).lower()
    destination = _value(record, "destination", "dest", "ip.dst", "dns.qry.name")
    if destination and not get_settings().network_store_ip_addresses:
        try:
            ipaddress.ip_address(str(destination))
        except ValueError:
            pass
        else:
            destination = None
    normalized = {
        "observed_at": _timestamp(_value(record, "observed_at", "timestamp", "frame.time")),
        "protocol": protocol,
        "source_category": str(_value(record, "source_category", "source") or "unknown")[:80],
        "destination": str(destination)[:255] if destination else None,
        "duration_seconds": _number(_value(record, "duration_seconds", "duration"), "duration_seconds"),
        "packet_count": _integer(_value(record, "packet_count", "packets"), "packet_count"),
        "byte_count": _integer(_value(record, "byte_count", "bytes", "frame.len"), "byte_count"),
        "observation_source": source,
        "observation_method": "tshark-export",
        "confidence": "metadata",
    }
    fingerprint = "|".join(str(normalized[key]) for key in (
        "observed_at", "protocol", "source_category", "destination",
        "duration_seconds", "packet_count", "byte_count",
    ))
    normalized["dedupe_key"] = hashlib.sha256(fingerprint.encode()).hexdigest()
    return normalized


def parse_export(content: bytes, filename: str) -> list[dict[str, Any]]:
    try:
        if filename.lower().endswith(".json"):
            parsed = json.loads(content.decode("utf-8"))
            records = parsed if isinstance(parsed, list) else parsed.get("records", [])
            if not isinstance(records, list):
                raise ImportErrorDetail("JSON must contain an array of records")
            return [item for item in records if isinstance(item, dict)]
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not rows.fieldnames:
            raise ImportErrorDetail("CSV header is required")
        return [dict(row) for row in rows]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportErrorDetail("unsupported or malformed export") from exc


def import_export(
    db: Session, content: bytes, filename: str, source: str = "imported",
    method: str = "tshark-export",
) -> tuple[int, int]:
    records = parse_export(content, filename)
    imported = 0
    duplicates = 0
    seen_keys: set[str] = set()
    for record in records:
        normalized = normalize_record(record, source)
        normalized["observation_method"] = method
        dedupe_key = normalized["dedupe_key"]
        if dedupe_key in seen_keys or db.query(NetworkObservation.id).filter_by(dedupe_key=dedupe_key).first():
            duplicates += 1
            continue
        db.add(NetworkObservation(**normalized))
        seen_keys.add(dedupe_key)
        imported += 1
    db.commit()
    return imported, duplicates


def delete_old_observations(db: Session, retention_days: int | None = None) -> int:
    days = retention_days if retention_days is not None else get_settings().observation_retention_days
    if days < 1:
        raise ValueError("retention_days must be at least 1")
    cutoff = utcnow().replace(microsecond=0)
    from datetime import timedelta
    cutoff -= timedelta(days=days)
    result = db.execute(delete(NetworkObservation).where(NetworkObservation.observed_at < cutoff))
    db.commit()
    return result.rowcount or 0
