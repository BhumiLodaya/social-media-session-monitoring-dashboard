from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.database_url.startswith("sqlite:///./"):
    Path("data").mkdir(exist_ok=True)
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def initialize_database(database_engine=engine) -> None:
    """Create tables and apply additive migrations without replacing existing data."""
    Base.metadata.create_all(bind=database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version VARCHAR(100) PRIMARY KEY)"
            )
        )
        columns = {column["name"] for column in inspect(connection).get_columns("provider_connections")}
        additions = {
            "connection_mode": "VARCHAR(20) NOT NULL DEFAULT 'mock'",
            "authorization_status": "VARCHAR(30) NOT NULL DEFAULT 'not_authorized'",
            "health_status": "VARCHAR(20) NOT NULL DEFAULT 'unknown'",
            "last_checked_at": "DATETIME",
            "authorization_expires_at": "DATETIME",
            "error_code": "VARCHAR(80)",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE provider_connections ADD COLUMN {name} {definition}"))

        if "provider_connection_state_v1" not in {
            row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }:
            connection.execute(
                text(
                    "UPDATE provider_connections "
                    "SET connection_mode = COALESCE(connection_mode, 'mock'), "
                    "authorization_status = CASE "
                    "WHEN status = 'healthy' THEN 'authorized' "
                    "WHEN status = 'expired' THEN 'expired' "
                    "WHEN status = 'revoked' THEN 'revoked' "
                    "ELSE 'not_authorized' END, "
                    "health_status = CASE "
                    "WHEN status IN ('healthy', 'unavailable', 'error') THEN status "
                    "ELSE 'unknown' END, "
                    "error_code = CASE "
                    "WHEN status = 'error' THEN 'provider_error' ELSE error_code END"
                )
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('provider_connection_state_v1')")
            )
        if "browser_activity_v1" not in {
            row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }:
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('browser_activity_v1')")
            )
        if "browser_activity_pairing_v1" not in {
            row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS browser_extension_pairing_codes ("
                    "id INTEGER PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "code_hash VARCHAR(64) NOT NULL UNIQUE, "
                    "created_at DATETIME NOT NULL, "
                    "expires_at DATETIME NOT NULL, "
                    "used_at DATETIME)"
                )
            )
            event_columns = {
                column["name"]
                for column in inspect(connection).get_columns("browser_activity_events")
            }
            if "idempotency_key" not in event_columns:
                connection.execute(
                    text(
                        "ALTER TABLE browser_activity_events "
                        "ADD COLUMN idempotency_key VARCHAR(128)"
                    )
                )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_browser_activity_device_idempotency "
                    "ON browser_activity_events (extension_device_id, idempotency_key)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version) "
                    "VALUES ('browser_activity_pairing_v1')"
                )
            )
        if "session_inventory_v1" not in {
            row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS session_inventory ("
                    "id INTEGER PRIMARY KEY, "
                    "user_id INTEGER NOT NULL REFERENCES users(id), "
                    "platform VARCHAR(30) NOT NULL, "
                    "session_type VARCHAR(30) NOT NULL, "
                    "created_at DATETIME NOT NULL, "
                    "last_observed_activity DATETIME, "
                    "status VARCHAR(20) NOT NULL DEFAULT 'unknown', "
                    "expires_at DATETIME, "
                    "last_status_check DATETIME NOT NULL, "
                    "status_reason VARCHAR(255) NOT NULL, "
                    "browser_process_status VARCHAR(20) NOT NULL DEFAULT 'unknown', "
                    "authentication_status VARCHAR(30) NOT NULL DEFAULT 'unverified', "
                    "revoked_at DATETIME)"
                )
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('session_inventory_v1')")
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
