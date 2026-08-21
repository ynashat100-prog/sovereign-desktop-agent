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


def test_terminal_tool_is_dangerous_even_for_read_only_commands():
    manager = PermissionManager()
    assert manager.permission_for("terminal.run", {"command": "dir"}) == PermissionLevel.DANGEROUS
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
        manager.request("run-1", "test-session", call)
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


def test_model_tool_protocol_is_parsed_and_unknown_tools_are_rejected():
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    service.permissions = PermissionManager()
    tool = service._parse_tool('TOOL: clipboard.write | {"text":"hello"} | copy requested text')
    assert tool is not None
    assert tool.name == "clipboard.write"
    assert tool.arguments == {"text": "hello"}

    try:
        service._parse_tool("TOOL: system.unlisted | {} | bypass policy")
    except ValueError as exc:
        assert "allow-listed" in str(exc)
    else:
        raise AssertionError("Unknown tools must be rejected before permission handling")


def test_allow_always_is_scoped_to_exact_tool_arguments():
    manager = PermissionManager()
    original = ToolCall(
        name="clipboard.write",
        arguments={"text": "approved"},
        permission=PermissionLevel.CONFIRM,
        rationale="requested",
    )
    manager.request("run-1", "session-1", original)
    manager.decide("run-1", "session-1", "allow_always")
    assert not manager.requires_approval(original, "session-1")
    assert manager.requires_approval(original, "session-2")

    different = original.model_copy(update={"arguments": {"text": "different"}})
    assert manager.requires_approval(different, "session-1")


def test_content_tools_reject_paths_outside_user_content_folders(monkeypatch, tmp_path):
    import app.tools.catalog as catalog

    for folder in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        (tmp_path / folder).mkdir()
    secret = tmp_path / ".ssh" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(catalog.Path, "home", classmethod(lambda cls: tmp_path))

    try:
        catalog.TOOLS["filesystem.read_text"].handler({"path": str(secret)})
    except PermissionError as exc:
        assert "limited" in str(exc)
    else:
        raise AssertionError("Reading secrets outside content folders must be refused")


def test_content_search_stops_at_the_result_limit(monkeypatch, tmp_path):
    import app.tools.catalog as catalog

    documents = tmp_path / "Documents"
    documents.mkdir()
    for index in range(60):
        (documents / f"file-{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(catalog.Path, "home", classmethod(lambda cls: tmp_path))

    result = catalog.TOOLS["filesystem.search"].handler({"root": str(documents), "pattern": "*.txt"})
    assert len(result["matches"]) == 50
    assert result["truncated"] is True


def test_application_open_rejects_command_interpreters_and_arguments():
    import app.tools.catalog as catalog

    for payload in ({"executable": "powershell.exe"}, {"executable": "notepad.exe", "args": ["file.txt"]}):
        try:
            catalog.TOOLS["application.open"].handler(payload)
        except (PermissionError, ValueError):
            continue
        raise AssertionError("Application open must not accept command interpreter or free arguments")


def test_router_does_not_match_substrings_inside_regular_words():
    router = SmartRouter()
    assert not router.is_simple("I sometimes commute after work")
    assert not router.is_simple("This is an open-ended discussion")


def test_stop_with_unknown_run_id_does_not_stop_other_runs():
    from app.core.state_machine import AgentRun
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    active = AgentRun("active-run")
    active.transition(RunState.ROUTING)
    service.runs = {"active-run": active}
    service.permissions = PermissionManager()

    assert service.stop("unknown-run") == 0
    assert active.state == RunState.ROUTING


def test_rejected_foreign_session_keeps_the_owner_request_pending():
    manager = PermissionManager()
    tool = ToolCall(
        name="clipboard.write",
        arguments={"text": "owned"},
        permission=PermissionLevel.CONFIRM,
        rationale="requested",
    )
    manager.request("run-1", "owner-session", tool)

    try:
        manager.decide("run-1", "attacker-session", "allow_once")
    except PermissionError as exc:
        assert "different session" in str(exc)
    else:
        raise AssertionError("A non-owning session must not decide another session's request")

    assert manager.has_pending("run-1")
    assert manager.decide("run-1", "owner-session", "allow_once") == tool


def test_malformed_tool_line_is_repaired_for_non_dangerous_tools():
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    service.permissions = PermissionManager()
    tool = service._parse_tool(
        "Here is the plan.\n```\nTOOL: filesystem.read_text | Documents/notes.txt | read notes\n```"
    )
    assert tool is not None
    assert tool.name == "filesystem.read_text"
    assert tool.arguments == {"path": "Documents/notes.txt"}


def test_malformed_dangerous_tool_line_is_rejected_instead_of_guessed():
    from app.services.agent import AgentService

    service = object.__new__(AgentService)
    service.permissions = PermissionManager()
    try:
        service._parse_tool("TOOL: filesystem.delete | /etc/hosts | cleanup")
    except ValueError as exc:
        assert "Malformed tool request" in str(exc)
    else:
        raise AssertionError("A malformed dangerous request must never be repaired")


def test_tool_protocol_and_echoed_instructions_never_reach_the_user():
    from app.services.agent import AgentService

    message = AgentService._user_message(
        "الملف يحتوي على الميزانية.\n"
        "The permission engine—not you—decides whether an action runs. "
        "For ordinary questions, respond normally and concisely.\n"
        'TOOL: filesystem.read_text | {"path":"notes.txt"} | read'
    )
    assert "TOOL:" not in message
    assert "permission engine" not in message
    assert "الميزانية" in message

    try:
        AgentService._user_message('TOOL: filesystem.read_text | {"path":"notes.txt"} | read')
    except ValueError as exc:
        assert "unusable" in str(exc)
    else:
        raise AssertionError("A reply that is only protocol must not be shown to the user")


def test_internal_failures_are_reported_as_stable_localizable_codes():
    from app.services.agent import AgentService

    assert AgentService._failure_code(PermissionError("Dangerous tools are disabled in Settings")) == "DANGEROUS_TOOLS_DISABLED"
    assert AgentService._failure_code(PermissionError("File tools are limited to Desktop")) == "FILE_SCOPE_BLOCKED"
    assert AgentService._failure_code(ValueError("Tool is not allow-listed: dir")) == "TOOL_NOT_ALLOWED"
    assert AgentService._failure_code(ValueError("Invalid tool JSON: bad")) == "MODEL_OUTPUT_UNUSABLE"
    assert AgentService._failure_code(FileNotFoundError("missing")) == "PATH_NOT_FOUND"
    assert AgentService._failure_code(RuntimeError("boom")) == "RUNTIME_ERROR"
