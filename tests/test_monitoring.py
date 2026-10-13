import pytest
from sqlalchemy import create_engine, text

from app.config import Settings
from app.database import initialize_database
from app.models.monitoring import NetworkObservation
from app.models.monitoring import ProviderConnection
from app.services.providers import MockProvider, sync_connection
from app.time import utcnow
from tests.conftest import login


def test_tshark_protocol_field_is_normalized_and_unknown_is_preserved(client):
    api, _ = client
    login(api)
    content = (
        b"timestamp,_ws.col.protocol,source_category,bytes\n"
        b"2026-10-12T10:00:00Z,TLSv1.2,workstation,558\n"
        b"2026-10-12T10:00:01Z,,workstation,60\n"
        b"2026-10-12T10:00:02Z,not-a-supported-protocol,workstation,60\n"
    )

    response = api.post("/monitoring/network/import?filename=tshark.csv", content=content)

    assert response.json() == {"imported": 3, "duplicates": 0}
    protocols = [item["protocol"] for item in api.get("/monitoring/network").json()]
    assert protocols == ["other", "other", "tls"]


def test_csv_import_normalizes_redacts_and_deduplicates(client):
    api, db_factory = client
    login(api)
    csv = (
        b"timestamp,protocol,source_category,destination,packets,bytes\n"
        b"2026-10-12T10:00:00Z,DNS,workstation,192.0.2.10,2,120\n"
    )
    first = api.post("/monitoring/network/import?filename=trace.csv", content=csv)
    assert first.json() == {"imported": 1, "duplicates": 0}
    assert api.post("/monitoring/network/import?filename=trace.csv", content=csv).json() == {
        "imported": 0, "duplicates": 1
    }
    observation = api.get("/monitoring/network").json()[0]
    assert observation["protocol"] == "dns"
    assert observation["destination"] is None
    with db_factory() as db:
        assert db.query(NetworkObservation).count() == 1


def test_csv_import_deduplicates_records_within_one_batch(client):
    api, _ = client
    login(api)
    csv = (
        b"timestamp,protocol,source_category,destination,packets,bytes\n"
        b"2026-10-12T10:00:00Z,DNS,workstation,192.0.2.10,2,120\n"
        b"2026-10-12T10:00:00Z,DNS,workstation,192.0.2.10,2,120\n"
    )
    response = api.post("/monitoring/network/import?filename=duplicate-batch.csv", content=csv)
    assert response.json() == {"imported": 1, "duplicates": 1}


def test_json_validation_and_network_stats(client):
    api, _ = client
    login(api)
    invalid = api.post(
        "/monitoring/network/import?filename=trace.json",
        content=b'{"records": [{"timestamp": "not-a-date"}]}',
    )
    assert invalid.status_code == 422
    imported = api.post(
        "/monitoring/network/import?filename=trace.json",
        content=b'{"records": [{"timestamp": "2026-10-12T10:00:00Z", "protocol": "TLS"}]}',
    )
    assert imported.json()["imported"] == 1
    stats = api.get("/monitoring/network/stats").json()
    assert stats["total"] == 1
    assert stats["by_protocol"] == {"tls": 1}
    malformed = api.post(
        "/monitoring/network/import?filename=bad.csv",
        content=b"timestamp,protocol,duration\n2026-10-12T10:00:00Z,TCP,nope\n",
    )
    assert malformed.status_code == 422


def test_provider_and_consent_are_owned_and_safe(client):
    api, _ = client
    login(api)
    connection = api.post(
        "/monitoring/connections",
        json={"provider": "mock", "external_account_id": "synthetic-1"},
    )
    assert connection.status_code == 201
    assert connection.json()["status"] == "healthy"
    body = connection.json()
    assert body["connection_mode"] == "mock"
    assert body["authorization_status"] == "authorized"
    assert body["health_status"] == "healthy"
    assert body["last_checked_at"] is not None
    assert "token" not in connection.text.lower()
    assert api.post(
        "/monitoring/connections",
        json={"provider": "instagram", "external_account_id": "real"},
    ).status_code == 501
    consent = api.post(
        "/monitoring/consent",
        json={"website": "local.example", "choice": "accepted", "policy_version": "v1"},
    )
    assert consent.status_code == 201
    assert api.get("/monitoring/consent").json()[0]["choice"] == "accepted"


@pytest.mark.parametrize(
    ("scenario", "authorization_status", "health_status", "error_code"),
    [
        ("healthy", "authorized", "healthy", None),
        ("unavailable", "authorized", "unavailable", "provider_unavailable"),
        ("expired", "expired", "unknown", "authorization_expired"),
        ("permission_denied", "unsupported", "unknown", "permission_denied"),
        ("provider_error", "not_authorized", "error", "provider_error"),
    ],
)
def test_mock_provider_scenarios_and_check_timestamp(
    client, scenario, authorization_status, health_status, error_code
):
    api, _ = client
    login(api)
    response = api.post(
        "/monitoring/connections",
        json={"provider": "mock", "external_account_id": f"synthetic-{scenario}", "scenario": scenario},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["connection_mode"] == "mock"
    assert body["authorization_status"] == authorization_status
    assert body["health_status"] == health_status
    assert body["error_code"] == error_code
    assert body["last_checked_at"] is not None


def test_provider_authorization_expiry_is_enforced(client):
    api, db_factory = client
    login(api)
    connection = api.post(
        "/monitoring/connections",
        json={"provider": "mock", "external_account_id": "expiring"},
    ).json()
    with db_factory() as db:
        item = db.get(ProviderConnection, connection["id"])
        item.authorization_expires_at = utcnow()
        db.commit()
    checked = api.post(f"/monitoring/connections/{connection['id']}/sync")
    assert checked.status_code == 200
    assert checked.json()["authorization_status"] == "expired"
    assert checked.json()["error_code"] == "authorization_expired"
    assert checked.json()["last_checked_at"] is not None


def test_sync_connection_records_timestamp_on_provider_error(client):
    api, db_factory = client
    login(api)
    connection = api.post(
        "/monitoring/connections",
        json={"provider": "mock", "external_account_id": "error"},
    ).json()
    with db_factory() as db:
        item = db.get(ProviderConnection, connection["id"])
        before = item.last_checked_at
        sync_connection(db, item, MockProvider("provider_error"))
        assert item.health_status == "error"
        assert item.error_code == "provider_error"
        assert item.last_checked_at is not None
        assert item.last_checked_at >= before


def test_provider_connection_migration_preserves_existing_data(tmp_path):
    database_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with database_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE provider_connections ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
                "provider VARCHAR(40) NOT NULL, external_account_id VARCHAR(255) NOT NULL, "
                "status VARCHAR(40) NOT NULL, last_sync_at DATETIME, "
                "error_message VARCHAR(255), created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO provider_connections "
                "(id, user_id, provider, external_account_id, status, created_at) "
                "VALUES (7, 3, 'mock', 'legacy-account', 'healthy', '2026-10-12 10:00:00')"
            )
        )

    initialize_database(database_engine)

    with database_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT user_id, external_account_id, status, connection_mode, "
                "authorization_status, health_status FROM provider_connections WHERE id = 7"
            )
        ).one()
        assert row == (3, "legacy-account", "healthy", "mock", "authorized", "healthy")


def test_retention_deletes_old_observations(client):
    api, db_factory = client
    login(api)
    api.post(
        "/monitoring/network/import?filename=old.csv",
        content=b"timestamp,protocol\n2020-01-01T00:00:00Z,DNS\n",
    )
    with db_factory() as db:
        assert db.query(NetworkObservation).count() == 1
    result = api.post("/monitoring/network/retention?retention_days=1")
    assert result.json()["deleted"] == 1


def test_live_capture_is_optional_and_disabled_by_default(client, monkeypatch):
    api, _ = client
    monkeypatch.setattr(
        "app.services.tshark.get_settings",
        lambda: Settings(_env_file=None),
    )
    login(api)
    response = api.post("/monitoring/network/live")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]
