from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionResponse(BaseModel):
    id: int
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: str

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    page: int
    page_size: int


class SessionStats(BaseModel):
    total: int
    active: int
    expired: int
    revoked: int


class SessionEventResponse(BaseModel):
    id: int
    session_id: int
    event_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionEventListResponse(BaseModel):
    items: list[SessionEventResponse]
