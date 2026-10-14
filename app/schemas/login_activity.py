from datetime import datetime

from pydantic import BaseModel, Field


class LoginActivityItem(BaseModel):
    id: str
    occurred_at: datetime
    account_label: str
    platform: str
    event_type: str
    source: str
    status: str
    confidence: str
    device_label: str | None
    is_demo: bool
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class LoginActivityResponse(BaseModel):
    items: list[LoginActivityItem]
    total: int
    page: int
    page_size: int


class LoginActivityStats(BaseModel):
    recent_observed_events: int
    successful_dashboard_logins: int
    failed_dashboard_logins: int
    connected_social_accounts: int
    accounts_requiring_reconnection: int


class DemoActivityResponse(BaseModel):
    created: int
    message: str


class PanelOpenRequest(BaseModel):
    panel_id: str = Field(min_length=1, max_length=60)


class PanelOpenResponse(BaseModel):
    id: int
    panel_id: str
    occurred_at: datetime


class PanelUsageItem(BaseModel):
    id: int
    panel_id: str
    occurred_at: datetime
    username: str


class PanelUsageResponse(BaseModel):
    items: list[PanelUsageItem]
    total: int
    page: int
    page_size: int
