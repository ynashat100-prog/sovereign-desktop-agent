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
