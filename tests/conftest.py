import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_path=tmp_path / "gomate.db", deepseek_api_key="")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    def create_user(username="alice"):
        credentials = {"username": username, "password": "test-password-12345"}
        registered = client.post("/api/v1/auth/register", json=credentials)
        assert registered.status_code == 201
        response = client.post("/api/v1/auth/login", json=credentials)
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    return create_user
