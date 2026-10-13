from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NetworkObservationResponse(BaseModel):
    id: int
    observed_at: datetime
    protocol: str
    source_category: str
    destination: str | None
    duration_seconds: float | None
    packet_count: int | None
    byte_count: int | None
    observation_source: str
    observation_method: str
    confidence: str

    model_config = ConfigDict(from_attributes=True)


class NetworkStats(BaseModel):
    total: int
    by_protocol: dict[str, int]
    last_ingestion_at: datetime | None


class ProviderConnectionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    external_account_id: str = Field(min_length=1, max_length=255)
    scenario: str = Field(default="healthy", pattern="^(healthy|unavailable|expired|permission_denied|provider_error)$")


class ProviderConnectionResponse(BaseModel):
    id: int
    provider: str
    external_account_id: str
    connection_mode: str
    authorization_status: str
    health_status: str
    status: str
    last_checked_at: datetime | None
    authorization_expires_at: datetime | None
    last_sync_at: datetime | None
    error_code: str | None
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class ConsentEventCreate(BaseModel):
    website: str = Field(min_length=1, max_length=255)
    choice: str = Field(pattern="^(accepted|rejected|customized)$")
    policy_version: str = Field(min_length=1, max_length=80)


class ConsentEventResponse(BaseModel):
    id: int
    website: str
    choice: str
    policy_version: str
    occurred_at: datetime
    source: str

    model_config = ConfigDict(from_attributes=True)
