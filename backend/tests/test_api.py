from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import agent, app


def runtime_client() -> TestClient:
    return TestClient(app, headers={"X-Agent-Token": settings.agent_runtime_token})


def test_health_endpoint_remains_available_for_packaging_probe():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_control_api_rejects_request_without_runtime_token():
    with TestClient(app) as client:
        response = client.get("/v1/status")
    assert response.status_code == 401


def test_setup_endpoint_remains_available_with_runtime_token():
    with runtime_client() as client:
        response = client.get("/v1/setup")
    assert response.status_code == 200
    assert any(check["key"] == "ollama" for check in response.json()["checks"])


def test_demo_message_does_not_need_a_provider():
    with runtime_client() as client:
        response = client.post(
            "/v1/messages",
            json={"text": "Explain demo mode", "session_id": "test-session", "demo_mode": True},
        )
    assert response.status_code == 200
    assert "Demo Mode" in response.json()["message"]


def test_cloud_selection_requires_explicit_hybrid_consent():
    with runtime_client() as client:
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
    with runtime_client() as client:
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
    with runtime_client() as client:
        response = client.post("/v1/models/active", json={"model": "qwen2.5-coder:7b"})
    assert response.status_code == 200
    assert selected == ["qwen2.5-coder:7b"]
    assert response.json()["model"] == "qwen2.5-coder:7b"


def test_dangerous_tools_setting_starts_disabled_and_can_be_changed():
    agent.permissions.dangerous_tools_enabled = False
    with runtime_client() as client:
        initial = client.get("/v1/permissions/settings")
        changed = client.post("/v1/permissions/settings", json={"enabled": True})
        restored = client.post("/v1/permissions/settings", json={"enabled": False})
    assert initial.json() == {"enabled": False}
    assert changed.json() == {"enabled": True}
    assert restored.json() == {"enabled": False}


def test_local_screenshot_request_waits_for_explicit_confirmation():
    session_id = "permission-test"
    with runtime_client() as client:
        response = client.post("/v1/messages", json={"text": "خذ لقطة شاشة", "session_id": session_id})
        body = response.json()
        deny = client.post(
            "/v1/permissions",
            json={"run_id": body["run_id"], "session_id": session_id, "decision": "deny"},
        )
    assert response.status_code == 200
    assert body["state"] == "awaiting_permission"
    assert body["tool_calls"][0]["name"] == "system.screenshot"
    assert deny.status_code == 403


def test_permission_decision_rejects_a_different_session():
    with runtime_client() as client:
        response = client.post("/v1/messages", json={"text": "خذ لقطة شاشة", "session_id": "owner-session"})
        body = response.json()
        hijack = client.post(
            "/v1/permissions",
            json={"run_id": body["run_id"], "session_id": "other-session", "decision": "allow_once"},
        )
    assert response.status_code == 200
    assert hijack.status_code == 403
    assert "different session" in hijack.json()["detail"]


def test_trace_websocket_requires_trusted_origin_and_runtime_token():
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/v1/ws/trace-test",
                headers={"origin": "https://untrusted.example"},
                subprotocols=["agent-runtime", settings.agent_runtime_token],
            ):
                pass
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        else:
            raise AssertionError("Untrusted WebSocket origin must be rejected")

        with client.websocket_connect(
            "/v1/ws/trace-test",
            headers={"origin": "http://tauri.localhost"},
            subprotocols=["agent-runtime", settings.agent_runtime_token],
        ) as websocket:
            assert websocket.accepted_subprotocol == "agent-runtime"


def test_rejected_foreign_decision_keeps_the_owner_card_usable():
    session_id = "owner-session-recovery"
    with runtime_client() as client:
        response = client.post("/v1/messages", json={"text": "خذ لقطة شاشة", "session_id": session_id})
        run_id = response.json()["run_id"]
        hijack = client.post(
            "/v1/permissions",
            json={"run_id": run_id, "session_id": "attacker-session", "decision": "allow_once"},
        )
        owner = client.post(
            "/v1/permissions",
            json={"run_id": run_id, "session_id": session_id, "decision": "deny"},
        )
    assert hijack.status_code == 403
    assert owner.status_code == 403
    assert "denied" in owner.json()["detail"]
    assert run_id not in agent.runs


def test_runtime_failures_reach_the_client_as_codes_not_exception_text():
    with runtime_client() as client:
        response = client.post(
            "/v1/messages",
            json={"text": "احذف ملف Documents/report.txt", "session_id": "code-session"},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["state"] == "failed"
    assert body["message"] == "AGENT_ERROR:DANGEROUS_TOOLS_DISABLED"
