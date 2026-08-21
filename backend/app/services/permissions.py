"""Permission policy enforced by the runtime, never trusted to the client or model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import monotonic

from app.models.schemas import PermissionLevel, ToolCall
from app.tools.catalog import TOOLS

_APPROVAL_TTL_SECONDS = 120


@dataclass
class PendingApproval:
    run_id: str
    session_id: str
    tool_call: ToolCall
    created_at: float


class PermissionManager:
    def __init__(self) -> None:
        self._always_allowed: set[tuple[str, str]] = set()
        self._pending: dict[str, PendingApproval] = {}
        self.dangerous_tools_enabled = False

    @staticmethod
    def _scope(tool: ToolCall) -> str:
        """Create a deterministic, session-only permission scope for one exact action."""
        arguments = json.dumps(tool.arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(arguments.encode("utf-8")).hexdigest()
        return f"{tool.name}:{digest}"

    def _expire(self) -> None:
        cutoff = monotonic() - _APPROVAL_TTL_SECONDS
        self._pending = {
            run_id: pending
            for run_id, pending in self._pending.items()
            if pending.created_at >= cutoff
        }

    def permission_for(self, name: str, _: dict) -> PermissionLevel:
        registered = TOOLS.get(name)
        return registered.permission if registered else PermissionLevel.DANGEROUS

    def requires_approval(self, tool: ToolCall, session_id: str) -> bool:
        if tool.permission == PermissionLevel.DANGEROUS:
            return True
        return tool.permission == PermissionLevel.CONFIRM and (session_id, self._scope(tool)) not in self._always_allowed

    def request(self, run_id: str, session_id: str, tool: ToolCall) -> PendingApproval:
        self._expire()
        if tool.permission == PermissionLevel.DANGEROUS and not self.dangerous_tools_enabled:
            raise PermissionError("Dangerous tools are disabled in Settings")
        pending = PendingApproval(
            run_id=run_id,
            session_id=session_id,
            tool_call=tool,
            created_at=monotonic(),
        )
        self._pending[run_id] = pending
        return pending

    def has_pending(self, run_id: str) -> bool:
        """Report whether a run is still waiting for its owner to decide."""
        self._expire()
        return run_id in self._pending

    def decide(self, run_id: str, session_id: str, decision: str) -> ToolCall:
        self._expire()
        pending = self._pending.get(run_id)
        if not pending:
            raise KeyError("No pending permission request for this run")
        if pending.session_id != session_id:
            # An unauthorized attempt is an audit event, not a cancellation: the request stays
            # pending so the owning session can still answer its own confirmation card.
            raise PermissionError("Permission decision belongs to a different session")
        self._pending.pop(run_id, None)
        if decision == "deny":
            raise PermissionError("User denied permission")
        if decision == "allow_always" and pending.tool_call.permission != PermissionLevel.DANGEROUS:
            self._always_allowed.add((pending.session_id, self._scope(pending.tool_call)))
        return pending.tool_call

    def clear(self, run_id: str | None = None) -> None:
        if run_id:
            self._pending.pop(run_id, None)
        else:
            self._pending.clear()
