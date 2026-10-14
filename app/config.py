from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Social Media Session Dashboard"
    database_url: str = "sqlite:///./data/app.db"
    initial_admin_username: str | None = None
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 3600
    observation_retention_days: int = 90
    network_store_ip_addresses: bool = False
    network_capture_enabled: bool = False
    network_capture_interface: str | None = None
    network_capture_duration_seconds: int = Field(default=10, ge=1, le=3600)
    tshark_executable: str | None = None
    browser_extension_pairing_ttl_seconds: int = Field(default=300, ge=60, le=900)
    browser_extension_token_ttl_seconds: int = Field(default=2592000, ge=3600, le=31536000)
    browser_activity_inactivity_threshold_seconds: int = Field(default=300, ge=60, le=86400)
    meta_app_id: str | None = None
    meta_redirect_uri: str = "http://127.0.0.1:8000/social/oauth/callback"
    meta_oauth_scopes: str = ""
    meta_authorization_url: str = "https://www.facebook.com/v24.0/dialog/oauth"
    meta_demo_mode: bool = True
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
