import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

SUPPORTED_DOMAINS = frozenset({
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
})
BrowserActivityType = Literal[
    "domain_visit",
    "navigation",
    "tab_activated",
    "tab_deactivated",
    "visibility_changed",
    "duration_update",
]
MAX_METADATA_BYTES = 4096
FORBIDDEN_METADATA_KEYS = frozenset({
    "access_token",
    "authorization",
    "body",
    "cookie",
    "cookies",
    "content",
    "password",
    "password_hash",
    "request_headers",
    "session_token",
})
MetadataValue = StrictStr | StrictInt | StrictFloat | StrictBool | None


class BrowserExtensionDeviceCreate(BaseModel):
    installation_label: str = Field(min_length=1, max_length=100, strict=True)


class BrowserExtensionPairingStartResponse(BaseModel):
    pairing_code: str
    expires_at: datetime


class BrowserExtensionPairingExchange(BaseModel):
    pairing_code: str = Field(min_length=20, max_length=128, strict=True)
    installation_label: str = Field(min_length=1, max_length=100, strict=True)


class BrowserExtensionTokenResponse(BaseModel):
    device: "BrowserExtensionDeviceResponse"
    extension_token: str


class BrowserExtensionDeviceResponse(BaseModel):
    id: int
    user_id: int
    installation_label: str
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class BrowserActivityEventCreate(BaseModel):
    event_type: BrowserActivityType
    occurred_at: datetime
    domain: str = Field(min_length=1, max_length=253, strict=True)
    duration_seconds: float | None = Field(default=None, ge=0, le=86400, strict=True)
    metadata: dict[StrictStr, MetadataValue] = Field(
        default_factory=dict, max_length=20, strict=True
    )
    consent_version: str = Field(min_length=1, max_length=80, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128, strict=True)

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.strip().lower().rstrip(".")
        if domain not in SUPPORTED_DOMAINS:
            raise ValueError("domain is not supported")
        return domain

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[StrictStr, MetadataValue]) -> dict[StrictStr, MetadataValue]:
        if any(key.lower() in FORBIDDEN_METADATA_KEYS for key in value):
            raise ValueError("metadata contains a prohibited field")
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
        if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError("metadata exceeds the maximum size")
        return value


class BrowserActivityEventResponse(BaseModel):
    id: int
    user_id: int
    extension_device_id: int
    event_type: BrowserActivityType
    occurred_at: datetime
    domain: str
    duration_seconds: float | None
    metadata: dict[str, MetadataValue] = Field(validation_alias="metadata_json")
    consent_version: str
    source: str
    created_at: datetime
    idempotency_key: str | None

    model_config = ConfigDict(from_attributes=True)


class BrowserActivityStats(BaseModel):
    total: int
    by_domain: dict[str, int]
    by_event_type: dict[str, int]
    duration_seconds: float


class BrowserActivityPlatformStatus(BaseModel):
    platform: Literal["facebook", "instagram"]
    status: Literal["recently_active", "inactive", "unknown"]
    last_activity_at: datetime | None
    explanation: str


class BrowserActivityStatusResponse(BaseModel):
    inactivity_threshold_seconds: int
    items: list[BrowserActivityPlatformStatus]
