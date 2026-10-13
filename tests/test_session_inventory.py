from datetime import UTC, datetime, timedelta

from app.models.session_inventory import SessionInventoryRecord
from app.time import utcnow
from tests.conftest import login


def test_inventory_creation_status_refresh_expiry_and_revoke(client):
    api, db_factory = client
    login(api)

    demo = api.post(
        "/session-inventory",
        json={"platform": "demo", "session_type": "synthetic_demo"},
    )
    assert demo.status_code == 201
    assert demo.json()["status"] == "active"
    assert demo.json()["authentication_status"] == "unverified"

    controlled = api.post(
        "/session-inventory",
        json={
            "platform": "instagram",
            "session_type": "controlled_browser",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    assert controlled.status_code == 201
    assert controlled.json()["status"] == "unknown"
    assert controlled.json()["browser_process_status"] == "unknown"
    assert "not verified" in controlled.json()["status_reason"]

    record_id = controlled.json()["id"]
    assert api.post(f"/session-inventory/{record_id}/refresh").json()["status"] == "unknown"
    revoked = api.post(f"/session-inventory/{record_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert api.post(f"/session-inventory/{record_id}/revoke").json()["status"] == "revoked"

    with db_factory() as db:
        record = db.get(SessionInventoryRecord, record_id)
        record.revoked_at = None
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert api.post(f"/session-inventory/{record_id}/refresh").json()["status"] == "expired"


def test_inventory_ownership_and_validation(client):
    api, _ = client
    assert api.get("/session-inventory").status_code == 401
    login(api)
    created = api.post(
        "/session-inventory",
        json={"platform": "facebook", "session_type": "controlled_browser"},
    )
    assert created.status_code == 201
    record_id = created.json()["id"]

    assert api.post(
        "/session-inventory",
        json={"platform": "instagram", "session_type": "synthetic_demo"},
    ).status_code == 422
    assert api.post(
        "/session-inventory",
        json={"platform": "demo", "session_type": "controlled_browser"},
    ).status_code == 422

    from fastapi.testclient import TestClient
    from app.main import app

    bob = TestClient(app)
    login(bob, "bob", "BobPass123!")
    assert bob.get("/session-inventory").json()["total"] == 0
    assert bob.post(f"/session-inventory/{record_id}/revoke").status_code == 404


def test_inventory_migration_preserves_existing_data(client):
    api, db_factory = client
    login(api)
    assert api.get("/session-inventory").status_code == 200
    with db_factory() as db:
        assert db.query(SessionInventoryRecord).count() == 0
