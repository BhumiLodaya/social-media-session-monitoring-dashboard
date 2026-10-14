from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OAuthStartResponse(BaseModel):
    provider: str
    mode: str
    authorization_url: str | None
    state: str | None
    message: str


class ProviderConnectionSummary(BaseModel):
    id: int
    provider: str
    external_account_id: str
    connection_mode: str
    authorization_status: str
    health_status: str
    status: str
    scopes: list[str]
    consent_recorded_at: datetime | None
    authorization_expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ParticipantCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    provider_connection_id: int | None = None
    is_demo: bool = False


class ParticipantResponse(BaseModel):
    id: int
    display_name: str
    is_demo: bool
    provider: str
    provider_account_id: str | None
    provider_connection_id: int | None
    consent_status: str
    participation_status: str
    connection_health: str
    joined_at: datetime | None
    withdrawn_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParticipantCreateResponse(BaseModel):
    participant: ParticipantResponse
    consent_token: str


class PostMetricCreate(BaseModel):
    provider_connection_id: int
    external_post_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    published_at: datetime
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    reach: int | None = Field(default=None, ge=0)
    impressions: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    source: str = Field(default="live", pattern="^(live|demo)$")


class PostMetricResponse(PostMetricCreate):
    id: int
    connection_health: str
    authorization_status: str
    engagement_rate: float | None

    model_config = ConfigDict(from_attributes=True)


class DiagnosisResponse(BaseModel):
    connection_id: int
    source: str
    metric_notes: list[str]
    trend: str
    findings: list[str]
    recommendations: list[str]
    best_posts: list[PostMetricResponse]
    posts: list[PostMetricResponse]
    baseline_median_reach: int | None | None
    baseline_difference_reach: int | None | None
    baseline_difference_percentage: float | None | None
    baseline_comparable_count: int | None | None
    status: str | None | None
