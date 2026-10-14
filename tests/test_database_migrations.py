from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import initialize_database


def test_initialize_database_adds_columns_needed_by_activity_and_diagnosis():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, username VARCHAR(100) NOT NULL UNIQUE, "
            "password_hash VARCHAR(255) NOT NULL, is_active BOOLEAN NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO users (id, username, password_hash, is_active) "
            "VALUES (1, 'existing-user', 'existing-hash', 1)"
        ))
        connection.execute(text(
            "INSERT INTO users (id, username, password_hash, is_active) "
            "VALUES (2, 'demo-alice', 'demo-hash', 1)"
        ))
        connection.execute(text(
            "CREATE TABLE provider_connections ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, provider VARCHAR(40) NOT NULL, "
            "external_account_id VARCHAR(255) NOT NULL, status VARCHAR(40) NOT NULL, "
            "created_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE post_metrics ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, provider_connection_id INTEGER NOT NULL, "
            "external_post_id VARCHAR(255) NOT NULL, title VARCHAR(255) NOT NULL, "
            "published_at DATETIME NOT NULL, likes INTEGER, comments INTEGER, reach INTEGER, "
            "impressions INTEGER, source VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL)"
        ))

    initialize_database(engine)
    initialize_database(engine, initial_admin_username="existing-user")
    initialize_database(engine, initial_admin_username="demo-alice")

    provider_columns = {column["name"] for column in inspect(engine).get_columns("provider_connections")}
    metric_columns = {column["name"] for column in inspect(engine).get_columns("post_metrics")}
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "updated_at" in provider_columns
    assert {"shares", "saves"} <= metric_columns
    assert {"email", "created_at", "is_demo"} <= user_columns
    assert "role" in user_columns
    with engine.connect() as connection:
        existing = connection.execute(text(
            "SELECT username, password_hash, email, created_at, is_demo, role FROM users WHERE id = 1"
        )).one()
        demo = connection.execute(text(
            "SELECT is_demo, role FROM users WHERE id = 2"
        )).one()
    assert existing.username == "existing-user"
    assert existing.password_hash == "existing-hash"
    assert existing.email is None
    assert existing.created_at is None
    assert existing.is_demo == 0
    assert existing.role == "admin"
    assert demo.is_demo == 1
    assert demo.role == "user"
    assert "ix_users_is_demo" in {index["name"] for index in inspect(engine).get_indexes("users")}
    engine.dispose()
