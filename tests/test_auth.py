from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD, TEST_USERNAME


def test_protected_endpoint_rejects_missing_token(client: TestClient):
    response = client.get("/api/me")
    assert response.status_code == 401


def test_invalid_login_is_rejected(client: TestClient):
    response = client.post(
        "/api/login",
        json={"username": TEST_USERNAME, "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_me_logout_flow(client: TestClient):
    login = client.post(
        "/api/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    assert payload["token"]
    assert payload["admin"]["username"] == TEST_USERNAME

    headers = {"Authorization": f"Bearer {payload['token']}"}
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["username"] == TEST_USERNAME

    logout = client.post("/api/logout", headers=headers)
    assert logout.status_code == 200, logout.text
    assert logout.json()["ok"] is True

    expired = client.get("/api/me", headers=headers)
    assert expired.status_code == 401
