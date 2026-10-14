from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, initialize_database
from app.models.auth import User
from app.main import app
from app.models.browser_activity import (
    BrowserActivityEvent,
    BrowserExtensionDevice,
    BrowserExtensionPairingCode,
)
from app.models.monitoring import NetworkObservation
from app.models.session_inventory import SessionInventoryRecord
from app.schemas.browser_activity import BrowserActivityEventCreate
from tests.conftest import login


def test_extension_pairing_cors_preflight(client):
    api, _ = client
    extension_origin = "chrome-extension://abpecjecneifkjappocjphhfmehjlfcd"
    response = api.options(
        "/browser-extension/pairing/exchange",
        headers={
            "Origin": extension_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == extension_origin
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_extension_pairing_cors_rejects_web_origins(client):
    api, _ = client
    response = api.options(
        "/browser-extension/pairing/exchange",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_browser_activity_migration_is_additive_and_rerunnable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="preserved", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            NetworkObservation(
                observed_at=datetime(2026, 1, 1),
                protocol="dns",
                dedupe_key="preserved-network-row",
            )
        )
        db.commit()

    initialize_database(engine)
    initialize_database(engine)

    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "select name from sqlite_master where type='table'"
            )
        }
        migrations = [
            row[0]
            for row in connection.execute(text("select version from schema_migrations"))
        ]
    with sessions() as db:
        assert db.query(User).filter_by(username="preserved").count() == 1
        assert db.query(NetworkObservation).filter_by(dedupe_key="preserved-network-row").count() == 1
    assert {"browser_extension_devices", "browser_activity_events", "session_inventory"} <= tables
    assert migrations.count("browser_activity_v1") == 1
    assert migrations.count("session_inventory_v1") == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("domain", "example.com"),
        ("domain", "https://instagram.com/path"),
        ("event_type", "unknown"),
        ("occurred_at", datetime(2026, 1, 1)),
        ("duration_seconds", -1),
        ("duration_seconds", 86401),
    ],
)
def test_browser_activity_schema_rejects_invalid_values(field, value):
    payload = {
        "event_type": "navigation",
        "occurred_at": "2026-01-01T00:00:00Z",
        "domain": "instagram.com",
        "consent_version": "v1",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        BrowserActivityEventCreate.model_validate(payload)


def test_browser_activity_schema_normalizes_domain_and_timestamp():
    event = BrowserActivityEventCreate(
        event_type="navigation",
        occurred_at="2026-01-01T00:00:00+05:30",
        domain=" Instagram.com. ",
        duration_seconds=1.5,
        metadata={"tab": 1},
        consent_version="v1",
        idempotency_key="normalization-1",
    )

    assert event.domain == "instagram.com"
    assert event.occurred_at == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)


def test_browser_activity_schema_rejects_oversized_metadata():
    with pytest.raises(ValidationError):
        BrowserActivityEventCreate(
            event_type="navigation",
            occurred_at="2026-01-01T00:00:00Z",
            domain="instagram.com",
            metadata={"value": "x" * 4096},
            consent_version="v1",
        )


@pytest.mark.parametrize(
    "field",
    [
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
        "PaSsWoRd",
    ],
)
def test_browser_activity_schema_rejects_sensitive_metadata(field):
    with pytest.raises(ValidationError):
        BrowserActivityEventCreate(
            event_type="navigation",
            occurred_at="2026-01-01T00:00:00Z",
            domain="instagram.com",
            metadata={field: "not allowed"},
            consent_version="v1",
        )


def test_browser_activity_is_owned_by_user_and_separate_from_network():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        first = User(username="first", password_hash="hash")
        second = User(username="second", password_hash="hash")
        db.add_all([first, second])
        db.flush()
        device = BrowserExtensionDevice(
            user_id=first.id,
            installation_label="Chrome",
            token_hash="a" * 64,
        )
        db.add(device)
        db.flush()
        db.add(
            BrowserActivityEvent(
                user_id=first.id,
                extension_device_id=device.id,
                event_type="navigation",
                occurred_at=datetime(2026, 1, 1),
                domain="instagram.com",
                consent_version="v1",
            )
        )
        db.add(
            NetworkObservation(
                observed_at=datetime(2026, 1, 1),
                protocol="tls",
                dedupe_key="network-is-separate",
            )
        )
        db.commit()

        assert db.scalars(
            select(BrowserActivityEvent).where(BrowserActivityEvent.user_id == first.id)
        ).one().domain == "instagram.com"
        assert db.scalars(
            select(BrowserActivityEvent).where(BrowserActivityEvent.user_id == second.id)
        ).first() is None
        assert db.query(BrowserActivityEvent).count() == 1
        assert db.query(NetworkObservation).count() == 1


def test_pairing_is_single_use_and_only_hashes_extension_token(client):
    api, db_factory = client
    login(api)

    pairing = api.post("/browser-extension/pairing/start")
    assert pairing.status_code == 200
    code = pairing.json()["pairing_code"]
    assert code
    assert code == code.strip()
    exchanged = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Chrome"},
    )
    assert exchanged.status_code == 200
    token = exchanged.json()["extension_token"]
    assert len(token) >= 64
    assert token not in api.get("/browser-extension/devices").text
    with db_factory() as db:
        device = db.query(BrowserExtensionDevice).one()
        assert device.token_hash != token
        assert len(device.token_hash) == 64
        pairing_record = db.query(BrowserExtensionPairingCode).one()
        assert pairing_record.used_at is not None

    reused = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Second"},
    )
    assert reused.status_code == 401


def test_pairing_code_expiry_and_device_revocation_are_enforced(client):
    api, db_factory = client
    login(api)
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    with db_factory() as db:
        pairing = db.query(BrowserExtensionPairingCode).one()
        pairing.expires_at = datetime(2020, 1, 1)
        db.commit()
    assert api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Expired"},
    ).status_code == 401

    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Revoked"},
    ).json()["extension_token"]
    device_id = api.get("/browser-extension/devices").json()[0]["id"]
    assert api.post(f"/browser-extension/devices/{device_id}/revoke").status_code == 204
    assert api.post(
        "/browser-activity/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "navigation",
            "occurred_at": "2026-01-01T00:00:00Z",
            "domain": "instagram.com",
            "consent_version": "v1",
            "idempotency_key": "revoked-1",
        },
    ).status_code == 401

    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Expired device"},
    ).json()["extension_token"]
    with db_factory() as db:
        device = db.query(BrowserExtensionDevice).filter_by(
            installation_label="Expired device"
        ).one()
        device.expires_at = datetime(2020, 1, 1)
        db.commit()
    assert api.post(
        "/browser-activity/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "navigation",
            "occurred_at": "2026-01-01T00:00:00Z",
            "domain": "instagram.com",
            "consent_version": "v1",
            "idempotency_key": "expired-device-1",
        },
    ).status_code == 401


def test_extension_device_revocation_is_scoped_to_owning_user(client):
    api, _ = client
    login(api)
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Alice's browser"},
    ).json()["extension_token"]
    device_id = api.get("/browser-extension/devices").json()[0]["id"]

    other_user = TestClient(app)
    login(other_user, "bob", "BobPass123!")
    assert other_user.get("/browser-extension/devices").json() == []
    assert other_user.post(
        f"/browser-extension/devices/{device_id}/revoke"
    ).status_code == 404

    accepted = api.post(
        "/browser-activity/events",
        headers={"Authorization": "Bearer " + token},
        json={
            "event_type": "navigation",
            "occurred_at": datetime.now(UTC).isoformat(),
            "domain": "facebook.com",
            "consent_version": "v1",
            "idempotency_key": "still-owned",
        },
    )
    assert accepted.status_code == 200


def test_activity_post_requires_extension_token_and_gets_are_dashboard_owned(client):
    api, _ = client
    assert api.post(
        "/browser-activity/events",
        json={
            "event_type": "navigation",
            "occurred_at": "2026-01-01T00:00:00Z",
            "domain": "instagram.com",
            "consent_version": "v1",
            "idempotency_key": "cookie-1",
        },
    ).status_code == 401
    assert api.get("/browser-activity/events").status_code == 401
    login(api)
    assert api.get("/browser-activity/events").status_code == 200
    assert api.get("/browser-activity/stats").json()["total"] == 0


def test_activity_events_deduplicate_and_return_stats(client):
    api, _ = client
    login(api)
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Stats"},
    ).json()["extension_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "event_type": "navigation",
        "occurred_at": "2026-01-01T00:00:00Z",
        "domain": "Instagram.com.",
        "duration_seconds": 4.5,
        "metadata": {"tab_id": 4, "transition": "typed"},
        "consent_version": "v1",
        "idempotency_key": "event-1",
    }
    first = api.post("/browser-activity/events", headers=headers, json=payload)
    duplicate = api.post("/browser-activity/events", headers=headers, json=payload)
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.json()["metadata"] == {"tab_id": 4, "transition": "typed"}

    activity = api.get("/login-activity/events?event_type=navigation_observed").json()
    browser_event = activity["items"][0]
    assert browser_event["account_label"] == "alice"
    assert browser_event["status"] == "observed"
    assert browser_event["confidence"] == "unknown"
    assert browser_event["metadata"] == {"tab_id": 4, "transition": "typed"}
    assert browser_event["platform"] == "Instagram"

    stats = api.get("/browser-activity/stats").json()
    assert stats == {
        "total": 1,
        "by_domain": {"instagram.com": 1},
        "by_event_type": {"navigation": 1},
        "duration_seconds": 4.5,
    }


def test_activity_rejects_invalid_payloads_and_large_requests(client):
    api, _ = client
    login(api)
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Validation"},
    ).json()["extension_token"]
    headers = {"Authorization": f"Bearer {token}"}
    base = {
        "event_type": "navigation",
        "occurred_at": "2026-01-01T00:00:00Z",
        "domain": "instagram.com",
        "consent_version": "v1",
        "idempotency_key": "invalid-1",
    }
    invalid = {**base, "domain": "example.com"}
    assert api.post("/browser-activity/events", headers=headers, json=invalid).status_code == 422
    assert api.post(
        "/browser-activity/events",
        headers={**headers, "Content-Length": "20000"},
        json=base,
    ).status_code == 413


def test_activity_events_are_user_owned_and_separate_from_network(client):
    api, db_factory = client
    login(api)
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Owner"},
    ).json()["extension_token"]
    response = api.post(
        "/browser-activity/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "domain_visit",
            "occurred_at": "2026-01-01T00:00:00Z",
            "domain": "youtube.com",
            "consent_version": "v1",
            "idempotency_key": "owned-1",
        },
    )
    assert response.status_code == 200
    with db_factory() as db:
        assert db.query(BrowserActivityEvent).count() == 1
        assert db.query(NetworkObservation).count() == 0
    bob = TestClient(app)
    login(bob, "bob", "BobPass123!")
    assert bob.get("/browser-activity/events").json() == []
    assert bob.get("/browser-activity/stats").json()["total"] == 0


def test_facebook_instagram_filters_preserve_ownership_and_inventory_status(client):
    api, db_factory = client
    login(api)
    inventory = api.post(
        "/session-inventory",
        json={"platform": "instagram", "session_type": "controlled_browser"},
    )
    assert inventory.status_code == 201
    inventory_id = inventory.json()["id"]
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": "Social activity filter"},
    ).json()["extension_token"]
    headers = {"Authorization": f"Bearer {token}"}

    headers = {"Authorization": "Bearer " + token}
    for domain, key in (("facebook.com", "facebook-filter"), ("instagram.com", "instagram-filter")):
        response = api.post(
            "/browser-activity/events",
            headers=headers,
            json={
                "event_type": "navigation",
                "occurred_at": "2026-01-01T00:00:00Z",
                "domain": domain,
                "duration_seconds": 3,
                "consent_version": "v1",
                "idempotency_key": key,
            },
        )
        assert response.status_code == 200

    assert [event["domain"] for event in api.get(
        "/browser-activity/events?domain=facebook.com"
    ).json()] == ["facebook.com"]
    assert [event["domain"] for event in api.get(
        "/browser-activity/events?domain=instagram.com"
    ).json()] == ["instagram.com"]
    assert api.get("/browser-activity/events?domain=linkedin.com").json() == []

    with db_factory() as db:
        record = db.get(SessionInventoryRecord, inventory_id)
        assert record.last_observed_activity is None
        assert record.status == "unknown"
        assert record.authentication_status == "unverified"

    from fastapi.testclient import TestClient
    from app.main import app

    bob = TestClient(app)
    login(bob, "bob", "BobPass123!")
    assert bob.get("/browser-activity/events?domain=facebook.com").json() == []


def _pair_activity_device(api, label):
    code = api.post("/browser-extension/pairing/start").json()["pairing_code"]
    token = api.post(
        "/browser-extension/pairing/exchange",
        json={"pairing_code": code, "installation_label": label},
    ).json()["extension_token"]
    return {"Authorization": f"Bearer {token}"}


def test_platform_activity_status_reports_recent_activity_and_separates_platforms(client):
    api, _ = client
    login(api)
    headers = _pair_activity_device(api, "Recent status")
    occurred_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    response = api.post(
        "/browser-activity/events",
        headers=headers,
        json={
            "event_type": "navigation",
            "occurred_at": occurred_at,
            "domain": "facebook.com",
            "consent_version": "v1",
            "idempotency_key": "recent-facebook-status",
        },
    )
    assert response.status_code == 200

    status = api.get("/browser-activity/status")
    assert status.status_code == 200
    by_platform = {item["platform"]: item for item in status.json()["items"]}
    assert by_platform["facebook"]["status"] == "recently_active"
    assert by_platform["facebook"]["last_activity_at"] is not None
    assert by_platform["instagram"]["status"] == "inactive"
    assert "authenticated" not in by_platform["facebook"]["explanation"].lower()


def test_platform_activity_status_reports_stale_activity_as_inactive_when_monitoring_functions(client):
    api, _ = client
    login(api)
    headers = _pair_activity_device(api, "Stale status")
    occurred_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    response = api.post(
        "/browser-activity/events",
        headers=headers,
        json={
            "event_type": "navigation",
            "occurred_at": occurred_at,
            "domain": "instagram.com",
            "consent_version": "v1",
            "idempotency_key": "stale-instagram-status",
        },
    )
    assert response.status_code == 200

    status = api.get("/browser-activity/status")
    by_platform = {item["platform"]: item for item in status.json()["items"]}
    assert by_platform["instagram"]["status"] == "inactive"
    assert by_platform["instagram"]["last_activity_at"] is not None
    assert by_platform["facebook"]["status"] == "inactive"


def test_platform_activity_status_is_unknown_without_functioning_monitoring(client):
    api, _ = client
    login(api)

    status = api.get("/browser-activity/status")
    assert status.status_code == 200
    assert {item["status"] for item in status.json()["items"]} == {"unknown"}
    assert all(item["last_activity_at"] is None for item in status.json()["items"])


def test_platform_activity_status_is_unknown_when_device_is_stale(client,):
    api, db_factory = client
    login(api)
    _pair_activity_device(api, "Disconnected status")
    with db_factory() as db:
        device = db.query(BrowserExtensionDevice).one()
        device.last_seen_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
        db.commit()

    status = api.get("/browser-activity/status")
    assert status.status_code == 200
    assert {item["status"] for item in status.json()["items"]} == {"unknown"}
