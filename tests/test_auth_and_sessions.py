from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.auth import LocalSession
from app.models.auth import AuthAuditEvent
from app.models.auth import User
from app.services.auth import pwd_context
from app.time import utcnow
from tests.conftest import login


def test_login_hashing_and_protected_route(client):
    api, db_factory = client
    assert api.get("/auth/me").status_code == 401
    assert api.post("/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    result = login(api)
    assert result.status_code == 200
    assert api.get("/auth/me").json()["username"] == "alice"
    with db_factory() as db:
        events = db.query(AuthAuditEvent).all()
        assert any(event.success for event in events)
        assert all("AlicePass123!" not in event.account_label for event in events)


def test_password_hash_rejects_incorrect_password(client):
    api, db_factory = client
    with db_factory() as db:
        user = db.query(User).filter_by(username="alice").one()
        assert user.password_hash != "AlicePass123!"
        assert pwd_context.verify("AlicePass123!", user.password_hash)
        assert not pwd_context.verify("wrong", user.password_hash)


def test_owner_filtering_pagination_stats_and_invalid_input(client):
    api, _ = client
    login(api)
    login(api)
    assert api.get("/sessions?page_size=1").json()["total"] == 2
    assert len(api.get("/sessions?page=2&page_size=1").json()["items"]) == 1
    assert api.get("/sessions/stats").json()["total"] == 2
    assert api.get("/sessions?page=0").status_code == 422
    assert api.get("/sessions?status=bad").status_code == 422

    bob = TestClient(app)
    login(bob, "bob", "BobPass123!")
    assert bob.get("/sessions").json()["total"] == 1
    assert bob.get("/sessions/1").status_code == 404


def test_expiry_revocation_and_logout(client):
    api, db_factory = client
    login(api)
    with db_factory() as db:
        session = db.query(LocalSession).first()
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert session.status == "expired"
    assert api.get("/auth/me").status_code == 401

    login(api)
    sessions = api.get("/sessions").json()["items"]
    session_id = next(item["id"] for item in sessions if item["status"] == "expired")
    assert api.post(f"/sessions/{session_id}/revoke").json()["status"] == "revoked"
    assert api.post(f"/sessions/{session_id}/revoke").status_code == 200
    assert api.post("/auth/logout").status_code == 204


def test_dashboard_and_error_handling(client):
    api, _ = client
    assert api.get("/").status_code == 200
    dashboard_script = api.get("/static/dashboard.js")
    assert dashboard_script.status_code == 200
    script = dashboard_script.text
    dashboard = api.get("/")
    assert dashboard.status_code == 200
    assert dashboard.headers["cache-control"] == "no-store"
    assert 'id="browser-activity-panel"' in dashboard.text
    assert 'id="social-browser-activity-panel"' in dashboard.text
    assert 'id="social-browser-status-panel"' in dashboard.text
    assert "Browser activity status" in dashboard.text
    assert "Observed browser activity does not prove that a Facebook or Instagram account is authenticated." in dashboard.text
    assert "No Facebook or Instagram activity found." in script
    assert "Facebook and Instagram activity could not be loaded." in script
    assert 'id="browser-extension-monitoring-panel"' in dashboard.text
    assert 'id="session-inventory-panel"' in dashboard.text
    assert "Status reason" in dashboard.text
    assert "authentication" in dashboard.text.lower()
    assert "navigation event does not prove an Instagram login" in dashboard.text
    assert 'id="browser-activity-rows"' in dashboard.text
    assert "<th>Username</th><th>Metadata</th><th>Source</th>" in dashboard.text
    assert "<th>Device</th><th>Metadata</th>" in dashboard.text
    assert "function activityMetadata(value)" in script
    assert '["transition", "tab_id"]' in script
    assert 'api("/browser-activity/events?limit=100")' in script
    assert 'api("/browser-activity/events?domain=facebook.com&limit=100")' in script
    assert 'api("/browser-activity/events?domain=instagram.com&limit=100")' in script
    assert 'api("/browser-activity/status")' in script
    assert "social-browser-status-rows" in script
    assert "extensionToken" not in script
    assert "innerHTML" not in script
    assert "textContent" in script
    assert "/browser-extension/devices" in script
    assert "/session-inventory" in script
    assert "Refresh status" in script
    assert "Revoke device" in script
    assert "extension bearer" not in script.lower()
    assert "external_account_id" in script
    assert api.post("/auth/login", json={"username": "", "password": ""}).status_code == 422
    auth_bootstrap = script.split('api("/auth/me").then(user => {', 1)[1].split(
        "}).catch(error => {", 1
    )[0]
    assert auth_bootstrap.index("currentUser = user;") < auth_bootstrap.index("load();")


def test_local_demo_lifecycle_and_events(client):
    api, _ = client
    assert api.get("/demo").status_code == 200
    assert api.post("/demo/start").status_code == 200
    created = api.post("/demo/sessions", json={"duration_seconds": 30})
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert api.post(f"/demo/sessions/{session_id}/expire").json()["status"] == "expired"
    assert api.post(f"/sessions/{session_id}/revoke").json()["status"] == "revoked"
    events = api.get("/sessions/events").json()["items"]
    assert {event["event_type"] for event in events} >= {"created", "expired", "revoked"}
