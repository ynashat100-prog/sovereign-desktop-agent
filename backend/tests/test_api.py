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


def test_provider_model_discovery_endpoint(monkeypatch):
    async def _discover_models(*, base_url: str, api_key: str):
        assert base_url == "https://api.x.ai/v1"
        assert api_key == "test-key"
        return ["grok-4.6", "grok-3"]

    monkeypatch.setattr("app.main.provider_registry.discover_models", _discover_models)
    with TestClient(app) as client:
        response = client.post(
            "/v1/providers/discover-models",
            json={"base_url": "https://api.x.ai/v1", "api_key": "test-key"},
        )
    assert response.status_code == 200
    assert response.json()["models"] == ["grok-4.6", "grok-3"]


def test_active_ollama_model_endpoint(monkeypatch):
    from app.models.schemas import ProviderStatus

    async def _status():
        return ProviderStatus(
            id="ollama",
            name="Ollama",
            kind="local",
            available=True,
            detail="ready",
            models=["qwen2.5-coder:7b"],
        )

    selected: list[str] = []
    monkeypatch.setattr("app.main.ollama_provider.status", _status)
    monkeypatch.setattr("app.main.ollama_provider.set_active_model", selected.append)
    with TestClient(app) as client:
        response = client.post("/v1/models/active", json={"model": "qwen2.5-coder:7b"})
    assert response.status_code == 200
    assert selected == ["qwen2.5-coder:7b"]
    assert response.json()["model"] == "qwen2.5-coder:7b"


def test_dangerous_tools_setting_starts_disabled_and_can_be_changed():
    from app.main import agent

    agent.permissions.dangerous_tools_enabled = False
    with TestClient(app) as client:
        initial = client.get("/v1/permissions/settings")
        changed = client.post("/v1/permissions/settings", json={"enabled": True})
        restored = client.post("/v1/permissions/settings", json={"enabled": False})
    assert initial.status_code == 200
    assert initial.json() == {"enabled": False}
    assert changed.json() == {"enabled": True}
    assert restored.json() == {"enabled": False}


def test_local_screenshot_request_waits_for_explicit_confirmation():
    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            json={"text": "خذ لقطة شاشة", "session_id": "permission-test"},
        )
        body = response.json()
        deny = client.post(
            "/v1/permissions",
            json={"run_id": body["run_id"], "decision": "deny"},
        )
    assert response.status_code == 200
    assert body["state"] == "awaiting_permission"
    assert body["tool_calls"][0]["name"] == "system.screenshot"
    assert deny.status_code == 403
