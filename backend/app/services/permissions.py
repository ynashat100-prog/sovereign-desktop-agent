"""Permission policy. Tool safety is derived here, never accepted from model output."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from app.models.schemas import PermissionLevel, ToolCall
from app.tools.catalog import TOOLS

_SAFE_TERMINAL_PREFIXES = {
    "dir",
    "ls",
    "where",
    "which",
    "whoami",
    "pwd",
    "git status",
    "git log",
    "python --version",
    "node --version",
}


@dataclass
class PendingApproval:
    run_id: str
    tool_call: ToolCall
    created_at: float


class PermissionManager:
    def __init__(self) -> None:
        self._always_allowed: set[str] = set()
        self._pending: dict[str, PendingApproval] = {}
        self.dangerous_tools_enabled = False

    def permission_for(self, name: str, arguments: dict) -> PermissionLevel:
        registered = TOOLS.get(name)
        if not registered:
            return PermissionLevel.DANGEROUS
        if name != "terminal.run":
            return registered.permission
        raw = arguments.get("command", [])
        command = " ".join(raw) if isinstance(raw, list) else str(raw)
        normalized = command.strip().lower()
        if normalized in _SAFE_TERMINAL_PREFIXES:
            return PermissionLevel.CONFIRM
        return PermissionLevel.DANGEROUS

    def requires_approval(self, tool: ToolCall) -> bool:
        if tool.permission == PermissionLevel.DANGEROUS:
            return True
        return tool.permission == PermissionLevel.CONFIRM and tool.name not in self._always_allowed

    def request(self, run_id: str, tool: ToolCall) -> PendingApproval:
        if tool.permission == PermissionLevel.DANGEROUS and not self.dangerous_tools_enabled:
            raise PermissionError("Dangerous tools are disabled in Settings")
        pending = PendingApproval(run_id=run_id, tool_call=tool, created_at=monotonic())
        self._pending[run_id] = pending
        return pending

    def decide(self, run_id: str, decision: str) -> ToolCall:
        pending = self._pending.pop(run_id, None)
        if not pending:
            raise KeyError("No pending permission request for this run")
        if decision == "deny":
            raise PermissionError("User denied permission")
        if decision == "allow_always" and pending.tool_call.permission != PermissionLevel.DANGEROUS:
            self._always_allowed.add(pending.tool_call.name)
        return pending.tool_call

    def clear(self) -> None:
        self._pending.clear()
