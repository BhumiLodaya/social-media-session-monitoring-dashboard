from datetime import timedelta

from app.models.social import OAuthState, PostMetric
from app.models.auth import User
from app.time import utcnow
from tests.conftest import login


def test_oauth_state_is_required_single_use_and_demo_callback_is_safe(client):
    api, db_factory = client
    login(api)
    start = api.get("/social/oauth/meta/start")
    assert start.status_code == 200
    body = start.json()
    assert body["mode"] == "demo"
    assert "token" not in start.text.lower()
    assert api.get("/social/oauth/callback?code=demo").status_code == 400
    callback = api.get(
        f"/social/oauth/callback?state={body['state']}&code=demo"
    )
    assert callback.status_code == 200
    assert api.get(
        f"/social/oauth/callback?state={body['state']}&code=demo"
    ).status_code == 400
    with db_factory() as db:
        state = db.query(OAuthState).first()
        assert state.used_at is not None


def test_expired_and_provider_error_callbacks_are_rejected(client):
    api, db_factory = client
    login(api)
    start = api.get("/social/oauth/meta/start").json()
    with db_factory() as db:
        state = db.query(OAuthState).first()
        state.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert api.get(
        f"/social/oauth/callback?state={start['state']}&code=demo"
    ).status_code == 400
    assert api.get("/social/oauth/callback?state=bad&error=access_denied").status_code == 400


def test_participant_consent_actions_and_account_ownership(client):
    api, _ = client
    login(api)
    assert api.get("/social/oauth/meta/start").status_code == 200
    state = api.get("/social/oauth/meta/start").json()["state"]
    assert api.get(f"/social/oauth/callback?state={state}&code=demo").status_code == 200
    connection = api.get("/social/connections").json()[0]
    pending = api.post(
        "/social/participants",
        json={"display_name": "Consenting creator", "provider_connection_id": connection["id"]},
    )
    assert pending.status_code == 201
    participant_id = pending.json()["participant"]["id"]
    assert api.post(f"/social/participants/{participant_id}/join").status_code == 409
    consented = api.post(
        "/social/participants",
        json={"display_name": "Participant"},
    )
    assert consented.json()["participant"]["participation_status"] == "paused"
    consented_participant = api.post(
        f"/social/participants/{consented.json()['participant']['id']}/consent"
        f"?token={consented.json()['consent_token']}"
    )
    assert consented_participant.json()["participation_status"] == "active"
    assert api.post(f"/social/participants/{consented.json()['participant']['id']}/withdraw").json()[
        "participation_status"
    ] == "withdrawn"


def test_demo_diagnosis_formula_and_unavailable_metrics(client):
    api, _ = client
    login(api)
    assert api.post("/social/analytics/demo").status_code == 201
    diagnosis = api.get("/social/analytics/diagnosis")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["source"] == "synthetic_demo"
    assert body["best_posts"][0]["engagement_rate"] == 9.71
    assert body["baseline_median_reach"] == 1500
    assert body["baseline_difference_reach"] == 600
    assert body["baseline_difference_percentage"] == 40.0
    assert body["baseline_comparable_count"] == 2
    assert body["status"] == "Above baseline"
    assert api.post(
        "/social/analytics/posts",
        json={
            "provider_connection_id": body["connection_id"],
            "external_post_id": "no-reach",
            "title": "No reach",
            "published_at": "2026-10-14T10:00:00",
            "likes": 10,
            "comments": 2,
            "source": "demo",
        },
    ).json()["engagement_rate"] is None


def test_diagnosis_reports_insufficient_historical_baseline(client):
    api, db_factory = client
    login(api)
    assert api.post("/social/analytics/demo").status_code == 201
    with db_factory() as db:
        user = db.query(User).filter_by(username="alice").one()
        db.query(PostMetric).filter(
            PostMetric.user_id == user.id,
            PostMetric.external_post_id.in_(("demo-post-2", "demo-post-3")),
        ).delete(synchronize_session=False)
        db.commit()

    diagnosis = api.get("/social/analytics/diagnosis")
    assert diagnosis.status_code == 200
    body = diagnosis.json()
    assert body["source"] == "synthetic_demo"
    assert len(body["posts"]) == 1
    assert body["trend"] == "insufficient_data"
    assert body["baseline_median_reach"] is None
    assert body["baseline_comparable_count"] is None
    assert body["status"] is None


def test_demo_setup_is_idempotent_and_reset_preserves_real_records(client):
    api, db_factory = client
    login(api)
    assert api.post("/social/analytics/demo").status_code == 201
    assert api.post("/social/analytics/demo").status_code == 201
    connections = api.get("/social/connections").json()
    assert len([item for item in connections if item["connection_mode"] == "demo"]) == 1
    demo_connection_id = connections[0]["id"]
    created = api.post(
        "/social/participants",
        json={
            "display_name": "Synthetic creator A",
            "provider_connection_id": demo_connection_id,
            "is_demo": True,
        },
    )
    assert created.status_code == 201
    real = api.post("/social/participants", json={"display_name": "Real participant"})
    assert real.status_code == 201
    reset = api.delete("/social/demo-data")
    assert reset.status_code == 200
    assert reset.json()["metrics_deleted"] == 3
    remaining_participants = api.get("/social/participants").json()
    assert [item["display_name"] for item in remaining_participants] == ["Real participant"]
    assert api.get("/social/connections").json() == []
    with db_factory() as db:
        assert db.query(User).count() == 2
        assert all(not user.is_demo for user in db.query(User).all())


def test_social_endpoints_require_authentication(client):
    api, _ = client
    assert api.get("/social/connections").status_code == 401
    assert api.get("/social/participants").status_code == 401
    assert api.get("/social/analytics/diagnosis").status_code == 401


def test_synthetic_demo_session_activity_is_clearly_labeled(client):
    api, _ = client
    assert api.post("/demo/start").status_code == 200
    events = api.get("/login-activity/events?page_size=100").json()["items"]
    session_event = next(item for item in events if item["event_type"] == "session_created")
    assert session_event["account_label"] == "demo-alice"
    assert session_event["is_demo"] is True


def test_login_activity_is_owned_filtered_and_demo_idempotent(client):
    api, _ = client
    login(api)
    assert api.post("/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    assert api.post("/login-activity/demo").json()["created"] == 3
    assert api.post("/login-activity/demo").json()["created"] == 0
    activity = api.get("/login-activity/events?page_size=100")
    assert activity.status_code == 200
    items = activity.json()["items"]
    assert {item["status"] for item in items} >= {"confirmed", "observed", "unknown"}
    assert all(item["is_demo"] for item in items if item["source"] == "synthetic-demo")
    assert api.get("/login-activity/events?status=observed").json()["items"][0]["status"] == "observed"
    assert api.get("/login-activity/events?page=0").status_code == 422
    stats = api.get("/login-activity/stats").json()
    assert stats["successful_dashboard_logins"] >= 1
    assert stats["failed_dashboard_logins"] >= 1


def test_login_activity_includes_social_connection_state(client):
    api, _ = client
    login(api)
    start = api.get("/social/oauth/meta/start").json()
    callback = api.get(
        f"/social/oauth/callback?state={start['state']}&code=demo"
    )
    assert callback.status_code == 200
    connection_id = callback.json()["connection_id"]

    connected = api.get("/login-activity/events")
    assert connected.status_code == 200
    connection_event = next(
        item for item in connected.json()["items"]
        if item["id"] == f"oauth-{connection_id}"
    )
    assert connection_event["account_label"].startswith("demo-meta-")
    assert connection_event["is_demo"] is True

    assert api.delete(f"/social/connections/{connection_id}").status_code == 204
    disconnected = api.get("/login-activity/events")
    assert disconnected.status_code == 200
    disconnect_event = next(
        item for item in disconnected.json()["items"]
        if item["id"] == f"oauth-disconnect-{connection_id}"
    )
    assert disconnect_event["event_type"] == "social_disconnection"
