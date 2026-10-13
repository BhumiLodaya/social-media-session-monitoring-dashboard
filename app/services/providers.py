from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import ProviderConnection
from app.time import utcnow


class Provider(Protocol):
    name: str

    def sync(self, external_account_id: str) -> "ProviderResult":
        ...


MockScenario = Literal["healthy", "unavailable", "expired", "permission_denied", "provider_error"]


@dataclass(frozen=True)
class ProviderResult:
    health_status: str
    authorization_status: str
    error_code: str | None = None
    error_message: str | None = None
    authorization_expires_at: datetime | None = None


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MockProvider:
    name = "mock"

    def __init__(self, scenario: MockScenario = "healthy") -> None:
        self.scenario = scenario

    def sync(self, external_account_id: str) -> ProviderResult:
        del external_account_id
        if self.scenario == "healthy":
            return ProviderResult("healthy", "authorized")
        if self.scenario == "unavailable":
            return ProviderResult("unavailable", "authorized", "provider_unavailable", "Mock provider is unavailable")
        if self.scenario == "expired":
            return ProviderResult(
                "unknown",
                "expired",
                "authorization_expired",
                "Mock authorization has expired",
                utcnow(),
            )
        if self.scenario == "permission_denied":
            return ProviderResult("unknown", "unsupported", "permission_denied", "Mock permission was denied")
        raise ProviderError("provider_error", "Mock provider returned a deterministic error")


def sync_connection(db: Session, connection: ProviderConnection, provider: Provider) -> ProviderConnection:
    checked_at = utcnow()
    connection.last_checked_at = checked_at
    connection.last_sync_at = checked_at
    if connection.authorization_expires_at and connection.authorization_expires_at <= checked_at:
        connection.authorization_status = "expired"
        connection.health_status = "unknown"
        connection.status = "unknown"
        connection.error_code = "authorization_expired"
        connection.error_message = "Provider authorization has expired"
        db.commit()
        db.refresh(connection)
        return connection
    try:
        result = provider.sync(connection.external_account_id)
        connection.authorization_status = result.authorization_status
        connection.health_status = result.health_status
        connection.status = result.health_status
        connection.authorization_expires_at = result.authorization_expires_at
        connection.error_code = result.error_code
        connection.error_message = result.error_message
    except ProviderError as exc:
        connection.health_status = "error"
        connection.status = "error"
        connection.error_code = exc.code
        connection.error_message = str(exc)[:255]
    db.commit()
    db.refresh(connection)
    return connection


def get_connection(db: Session, user_id: int, connection_id: int) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id,
            ProviderConnection.user_id == user_id,
        )
    )
