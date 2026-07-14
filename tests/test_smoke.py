from fastapi.testclient import TestClient


def test_login_page_and_security_headers(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"].startswith("no-store")


def test_health_endpoints(client: TestClient):
    for path in ("/api/health", "/api/ui-health"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)


def test_expected_route_count(app_module):
    routes = [r for r in app_module.app.routes if getattr(r, "path", None)]
    assert len(routes) >= 147


def test_database_is_temporary_and_initialized(app_module):
    assert app_module.DB.exists()
    assert app_module.DB.name == "bblotto_v34.db"
    with app_module.con() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        admin_count = connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        draw_count = connection.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    assert integrity == "ok"
    assert admin_count == 1
    assert draw_count >= 100
