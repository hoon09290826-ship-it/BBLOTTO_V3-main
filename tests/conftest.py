"""Shared test setup for BBLOTTO.

Every test session uses a temporary SQLite directory.  The production DB is
never opened, copied, or modified by the test suite.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_USERNAME = "testadmin"
TEST_PASSWORD = "BbLotto-Test-2026!"


@pytest.fixture(scope="session")
def app_module(tmp_path_factory: pytest.TempPathFactory):
    db_dir = tmp_path_factory.mktemp("bblotto_test_db")
    export_dir = tmp_path_factory.mktemp("bblotto_test_exports")

    os.environ["BBLOTTO_DB_DIR"] = str(db_dir)
    os.environ["BBLOTTO_EXPORT_DIR"] = str(export_dir)
    os.environ["BBLOTTO_ADMIN_USERNAME"] = TEST_USERNAME
    os.environ["BBLOTTO_ADMIN_PASSWORD"] = TEST_PASSWORD
    os.environ["BBLOTTO_SECRET_KEY"] = "test-only-secret-key-not-for-production"
    os.environ["BBLOTTO_LOG_LEVEL"] = "WARNING"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("POSTGRES_URL", None)

    for module_name in list(sys.modules):
        if module_name == "backend.app" or module_name.startswith("backend.app."):
            sys.modules.pop(module_name, None)

    module = importlib.import_module("backend.app")
    assert Path(module.DB).parent == db_dir
    return module


@pytest.fixture(scope="session")
def client(app_module):
    with TestClient(app_module.app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    yield headers
    client.post("/api/logout", headers=headers)
