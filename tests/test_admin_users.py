from fastapi.testclient import TestClient

from app.main import app
from app.models.auth import AuthAuditEvent, LocalSession, SessionEvent, User
from tests.conftest import login


def test_admin_can_list_users_view_activity_and_manage_account_status(client):
    admin, db_factory = client
    with db_factory() as db:
        alice = db.query(User).filter_by(username="alice").one()
        alice.role = "admin"
        db.commit()

    assert login(admin).status_code == 200
    member = TestClient(app)
    assert login(member, "bob", "BobPass123!").status_code == 200

    users = admin.get("/users?page_size=100")
    assert users.status_code == 200
    assert {item["username"] for item in users.json()["items"]} == {"alice", "bob"}
    bob_id = next(item["id"] for item in users.json()["items"] if item["username"] == "bob")
    detail = admin.get(f"/users/{bob_id}/details")
    assert detail.status_code == 200
    assert detail.json()["created_at"] is not None
    assert detail.json()["last_login_at"] is not None
    assert "dashboard_login" in {
        event["event_type"] for event in detail.json()["recent_activity"]
    }

    deactivated = admin.patch(f"/users/{bob_id}/status", json={"is_active": False})
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["session_status"] == "Offline"
    assert member.get("/auth/me").status_code == 401
    with db_factory() as db:
        session = db.query(LocalSession).filter_by(user_id=bob_id).one()
        assert session.status == "revoked"
        assert db.query(SessionEvent).filter_by(
            session_id=session.id, event_type="revoked"
        ).count() == 1
        assert db.query(AuthAuditEvent).filter_by(
            user_id=bob_id, event_type="account_deactivated", source="admin"
        ).count() == 1

    activated = admin.patch(f"/users/{bob_id}/status", json={"is_active": True})
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    assert login(member, "bob", "BobPass123!").status_code == 200


def test_admin_cannot_deactivate_own_account_or_nonexistent_user(client):
    admin, db_factory = client
    with db_factory() as db:
        alice = db.query(User).filter_by(username="alice").one()
        alice_id = alice.id
        alice.role = "admin"
        db.commit()
    assert login(admin).status_code == 200

    self_deactivation = admin.patch(f"/users/{alice_id}/status", json={"is_active": False})
    assert self_deactivation.status_code == 409
    assert admin.patch("/users/999/status", json={"is_active": False}).status_code == 404
    with db_factory() as db:
        assert db.query(User).filter_by(role="admin", is_active=True).count() == 1
    bob_id = next(
        item["id"] for item in admin.get("/users").json()["items"]
        if item["username"] == "bob"
    )
    assert admin.get(f"/users/{bob_id}/details").status_code == 200
