from tests.conftest import login


def test_user_detail_page_and_api_routes_are_distinct(client):
    api, _ = client
    login(api)

    page = api.get("/users/1")
    assert page.status_code == 200
    assert "data-view=\"user-detail\"" in page.text
    users_page = api.get("/user-directory")
    assert users_page.status_code == 200
    assert 'href="/user-directory" data-nav="users"' in users_page.text
    monitoring_page = api.get("/monitoring")
    assert monitoring_page.status_code == 200
    assert "data-view=\"monitoring\"" in monitoring_page.text
    assert 'href="/monitoring" data-nav="monitoring"' in monitoring_page.text
    assert api.post("/login-activity/panels", json={"panel_id": "monitoring"}).status_code == 201
    sessions_page = api.get("/dashboard-sessions")
    assert sessions_page.status_code == 200
    assert 'href="/dashboard-sessions" data-nav="sessions"' in sessions_page.text

    detail = api.get("/users/1/details")
    assert detail.status_code == 200
    assert detail.json()["username"] == "alice"
    assert detail.json()["session_status"] == "Online"
    assert "password_hash" not in detail.json()


def test_users_api_returns_only_the_authenticated_users_private_data(client):
    api, _ = client
    login(api)
    assert api.get("/users").json()["items"][0]["username"] == "alice"

    from fastapi.testclient import TestClient
    from app.main import app

    bob = TestClient(app)
    login(bob, "bob", "BobPass123!")
    response = bob.get("/users")
    assert response.status_code == 200
    assert [item["username"] for item in response.json()["items"]] == ["bob"]
    assert bob.get("/users/1/details").status_code == 404
    assert bob.patch("/users/1/status", json={"is_active": False}).status_code == 403
    assert bob.get("/users?page=0").status_code == 422
