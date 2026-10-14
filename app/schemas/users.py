from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserActivityItem(BaseModel):
    id: str
    occurred_at: datetime
    event_type: str
    label: str
    source: str
    status: str


class UserSummary(BaseModel):
    id: int
    username: str
    email: str | None
    is_active: bool
    role: str
    is_demo: bool
    created_at: datetime | None
    last_login_at: datetime | None
    last_logout_at: datetime | None
    session_status: str

    model_config = ConfigDict(from_attributes=True)


class UserDetail(UserSummary):
    session_count: int
    active_session_count: int
    recent_activity: list[UserActivityItem]


class UserListResponse(BaseModel):
    items: list[UserSummary]
    total: int
    page: int
    page_size: int


class UserStatusUpdate(BaseModel):
    is_active: bool
