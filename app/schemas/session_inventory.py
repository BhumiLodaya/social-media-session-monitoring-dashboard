from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


Platform = Literal["instagram", "facebook", "demo"]
SessionType = Literal["controlled_browser", "synthetic_demo"]
SessionStatus = Literal["active", "inactive", "expired", "revoked", "unknown"]


class SessionInventoryCreate(BaseModel):
    platform: Platform
    session_type: SessionType
    expires_at: datetime | None = None


class SessionInventoryResponse(BaseModel):
    id: int
    user_id: int
    platform: str
    session_type: str
    created_at: datetime
    last_observed_activity: datetime | None
    status: str
    expires_at: datetime | None
    last_status_check: datetime
    status_reason: str
    browser_process_status: str
    authentication_status: str
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SessionInventoryListResponse(BaseModel):
    items: list[SessionInventoryResponse]
    total: int


class SessionInventoryStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_platform: dict[str, int]
