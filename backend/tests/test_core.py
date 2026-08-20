from app.core.state_machine import AgentRun
from app.models.schemas import PermissionLevel, RunState, ToolCall
from app.services.permissions import PermissionManager
from app.services.router import SmartRouter


def test_state_machine_rejects_invalid_transition():
    run = AgentRun("run-1")
    try:
        run.transition(RunState.COMPLETED)
    except ValueError as exc:
        assert "Invalid transition" in str(exc)
    else:
        raise AssertionError("Invalid transition must be rejected")


def test_state_machine_stops_active_run():
    run = AgentRun("run-1")
    run.transition(RunState.ROUTING)
    run.stop()
    assert run.state == RunState.STOPPED


def test_router_identifies_simple_request():
    assert SmartRouter().is_simple("ما الوقت الآن؟")
    assert not SmartRouter().is_simple("حلل مشروع برمجي كبير")


def test_permission_manager_owns_terminal_risk_classification():
    manager = PermissionManager()
    assert manager.permission_for("terminal.run", {"command": "dir"}) == PermissionLevel.CONFIRM
    assert manager.permission_for("terminal.run", {"command": "del important.txt"}) == PermissionLevel.DANGEROUS


def test_dangerous_tool_is_disabled_by_default():
    manager = PermissionManager()
    call = ToolCall(
        name="terminal.run",
        arguments={"command": "del x"},
        permission=PermissionLevel.DANGEROUS,
        rationale="requested",
    )
    try:
        manager.request("run-1", call)
    except PermissionError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("Dangerous commands must require the explicit Settings toggle")


class _AvailableProvider:
    def __init__(self, provider_id: str):
        self.id = provider_id

    async def status(self):
        from app.models.schemas import ProviderStatus
        return ProviderStatus(id=self.id, name=self.id, kind="local" if self.id == "ollama" else "cloud", available=True, detail="ready")


async def test_router_does_not_use_cloud_without_explicit_permission():
    router = SmartRouter()
    route = await router.route("Analyze a difficult project", [_AvailableProvider("cloud")], allow_cloud=False)
    assert route.mode == "demo"

    route = await router.route(
        "Analyze a difficult project",
        [_AvailableProvider("cloud")],
        preferred_provider="cloud",
        allow_cloud=True,
    )
    assert route.provider_id == "cloud"


class _MemoryCredentials:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_provider_registry_keeps_api_key_out_of_metadata_file(tmp_path):
    from app.services.provider_registry import ProviderRegistry

    path = tmp_path / "providers.json"
    registry = ProviderRegistry(path, _MemoryCredentials())
    record = registry.upsert(
        record_id="provider-1",
        name="Grok",
        base_url="https://api.x.ai/v1",
        model="grok-4.6",
        api_key="secret-value-1234",
        fallback_enabled=False,
        preset="xai",
    )

    assert record["api_key_masked"] == "••••••••••••1234"
    assert "secret-value-1234" not in path.read_text(encoding="utf-8")
    assert registry.secret("provider-1") == "secret-value-1234"


async def test_provider_model_discovery_returns_sorted_unique_model_ids(monkeypatch, tmp_path):
    from app.services.provider_registry import ProviderRegistry

    class _Response:
        is_success = True
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "grok-4.6"}, {"id": "grok-3"}, {"id": "grok-4.6"}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        @staticmethod
        async def get(*_, **__):
            return _Response()

    monkeypatch.setattr("app.services.provider_registry.httpx.AsyncClient", lambda **_: _Client())
    registry = ProviderRegistry(tmp_path / "providers.json", _MemoryCredentials())

    assert await registry.discover_models(base_url="https://api.x.ai/v1", api_key="key") == [
        "grok-3",
        "grok-4.6",
    ]


def test_deterministic_screenshot_request_requires_confirmation():
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    tool = service._deterministic_tool("خذ لقطة شاشة")
    assert tool is not None
    assert tool.name == "system.screenshot"
    assert tool.permission == PermissionLevel.CONFIRM


def test_deterministic_delete_request_remains_dangerous():
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    tool = service._deterministic_tool("احذف ملف C:\\Users\\me\\old.txt")
    assert tool is not None
    assert tool.name == "filesystem.delete"
    assert tool.permission == PermissionLevel.DANGEROUS


def test_system_credential_store_wraps_unexpected_backend_errors():
    from app.services.provider_registry import SystemCredentialStore

    class _BrokenBackend:
        priority = 5

        @staticmethod
        def set_password(*_):
            raise OSError("Windows credential service unavailable")

    store = SystemCredentialStore()
    store.backend = _BrokenBackend()
    try:
        store.set("service", "provider", "secret")
    except RuntimeError as exc:
        assert str(exc) == "Secure credential storage is unavailable"
    else:
        raise AssertionError("Credential storage errors must be normalized")
