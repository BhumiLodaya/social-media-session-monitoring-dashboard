from datetime import timedelta

from app.models.auth import AuthAuditEvent, LocalSession, SessionEvent, User
from app.routers.users import user_summary
from app.services.auth import pwd_context
from app.time import utcnow
from tests.conftest import login


def test_registration_validates_duplicates_and_stores_only_password_hash(client):
    api, db_factory = client
    password = "SyntheticPassphrase#2030"
    response = api.post("/auth/register", json={
        "username": "New.Member",
        "email": " New.Member@Example.Test ",
        "password": password,
        "role": "admin",
    })
    assert response.status_code == 201
    assert response.json()["username"] == "new.member"
    assert response.json()["email"] == "new.member@example.test"
    assert response.json()["role"] == "user"
    assert "password" not in response.json()
    assert "password_hash" not in response.json()

    with db_factory() as db:
        user = db.query(User).filter_by(username="new.member").one()
        assert user.email == "new.member@example.test"
        assert user.password_hash != password
        assert pwd_context.verify(password, user.password_hash)
        assert user.is_demo is False
        assert user.role == "user"
        assert user.created_at is not None
        assert user.created_at.tzinfo is None
        assert abs((utcnow() - user.created_at).total_seconds()) < 10
        assert db.query(AuthAuditEvent).filter_by(
            user_id=user.id, event_type="account_registered"
        ).count() == 1

    assert api.post("/auth/register", json={
        "username": "NEW.MEMBER",
        "email": "another@example.test",
        "password": password,
    }).status_code == 409
    assert api.post("/auth/register", json={
        "username": "another",
        "email": "NEW.MEMBER@example.test",
        "password": password,
    }).status_code == 409
    assert api.post("/auth/register", json={
        "username": "short",
        "email": "not-an-email",
        "password": "too-short",
    }).status_code == 422
    assert api.post("/auth/register", json={
        "username": "valid-name",
        "email": "not-an-email",
        "password": password,
    }).status_code == 422
    assert api.post("/auth/register", json={
        "username": "valid-name",
        "email": "valid@example.test",
        "password": "too-short",
    }).status_code == 422


def test_login_logout_failure_and_user_activity_are_owned_and_secret_free(client):
    api, db_factory = client
    response = api.post("/auth/register", json={
        "username": "activity-user",
        "email": "activity@example.test",
        "password": "SyntheticPassphrase#2031",
    })
    user_id = response.json()["id"]
    with db_factory() as db:
        assert user_summary(db, db.get(User, user_id)).session_status == "Offline"

    assert api.post("/auth/login", json={
        "username": "activity-user",
        "password": "SyntheticPassphrase#2031",
    }).status_code == 200
    summary = api.get("/users").json()["items"][0]
    assert summary["session_status"] == "Online"
    assert summary["last_login_at"] is not None
    assert summary["last_logout_at"] is None
    first_login_at = summary["last_login_at"]

    private_password = "NeverPersistThisSubmittedPassword#1"
    assert api.post("/auth/login", json={
        "username": "activity-user", "password": private_password
    }).status_code == 401
    assert api.post("/auth/login", json={
        "username": "unrecorded-visitor", "password": private_password
    }).status_code == 401

    detail = api.get(f"/users/{user_id}/details").json()
    activity_types = [event["event_type"] for event in detail["recent_activity"]]
    assert "account_registered" in activity_types
    assert "dashboard_login" in activity_types
    assert "dashboard_login_failed" in activity_types
    assert "session_created" in activity_types
    assert "password_hash" not in str(detail)
    events = api.get("/login-activity/events?page_size=100").json()["items"]
    assert any(item["event_type"] == "dashboard_login" and item["status"] == "confirmed" for item in events)
    assert all(private_password not in str(item) for item in events)
    activity_stats = api.get("/login-activity/stats").json()
    assert activity_stats["successful_dashboard_logins"] == 1
    assert activity_stats["failed_dashboard_logins"] == 1

    assert api.post("/auth/logout").status_code == 204
    assert api.get("/auth/me").status_code == 401
    assert api.post("/auth/logout").status_code == 204

    with db_factory() as db:
        user = db.get(User, user_id)
        logout_event = db.query(AuthAuditEvent).filter_by(
            user_id=user_id, event_type="dashboard_logout"
        ).one()
        failed_events = db.query(AuthAuditEvent).filter_by(
            user_id=user_id, event_type="dashboard_login", success=False
        ).all()
        unknown_events = db.query(AuthAuditEvent).filter(
            AuthAuditEvent.user_id.is_(None)
        ).all()
        assert user.username == "activity-user"
        assert logout_event.created_at.isoformat() >= first_login_at
        assert len(failed_events) == 1
        assert len(unknown_events) == 1
        assert unknown_events[0].account_label == "Unknown account"
        assert all(private_password not in event.account_label for event in failed_events + unknown_events)
        session = db.query(LocalSession).filter_by(user_id=user_id).one()
        assert session.status == "revoked"
        assert db.query(SessionEvent).filter_by(
            session_id=session.id, event_type="revoked"
        ).count() == 1


def test_expired_session_is_recorded_when_detected_and_account_status_is_separate(client):
    api, db_factory = client
    login(api)
    with db_factory() as db:
        user = db.query(User).filter_by(username="alice").one()
        user_id = user.id
        session = db.query(LocalSession).filter_by(user_id=user.id).one()
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    assert api.get("/auth/me").status_code == 401
    with db_factory() as db:
        session = db.query(LocalSession).filter_by(user_id=user_id).one()
        assert session.status == "expired"
        assert db.query(SessionEvent).filter_by(
            session_id=session.id, event_type="expired"
        ).count() == 1
        assert db.query(AuthAuditEvent).filter_by(
            user_id=user_id, event_type="dashboard_session_expired"
        ).count() == 1
        assert db.get(User, user_id).is_active is True
