from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_setup_endpoint_remains_available_without_ollama():
    with TestClient(app) as client:
        response = client.get("/v1/setup")
    assert response.status_code == 200
    body = response.json()
    assert any(check["key"] == "ollama" for check in body["checks"])


def test_demo_message_does_not_need_a_provider():
    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            json={"text": "Explain demo mode", "session_id": "test-session", "demo_mode": True},
        )
    assert response.status_code == 200
    assert "Demo Mode" in response.json()["message"]


def test_cloud_selection_requires_explicit_hybrid_consent():
    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            json={
                "text": "Use my cloud model",
                "session_id": "test-session",
                "selected_provider": "custom-provider",
                "privacy_mode": "local_only",
                "cloud_consent": False,
            },
        )
    assert response.status_code == 409
    assert "explicit consent" in response.json()["detail"]
