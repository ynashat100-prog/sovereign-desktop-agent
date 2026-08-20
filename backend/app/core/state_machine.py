"""Explicit, auditable lifecycle for every agent run."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event

from app.models.schemas import RunState

_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.IDLE: {RunState.ROUTING, RunState.STOPPED},
    RunState.ROUTING: {RunState.PLANNING, RunState.EXECUTING, RunState.FAILED, RunState.STOPPED},
    RunState.PLANNING: {
        RunState.AWAITING_PERMISSION,
        RunState.EXECUTING,
        RunState.REVIEWING,
        RunState.FAILED,
        RunState.STOPPED,
    },
    RunState.AWAITING_PERMISSION: {RunState.EXECUTING, RunState.FAILED, RunState.STOPPED},
    RunState.EXECUTING: {RunState.REVIEWING, RunState.COMPLETED, RunState.FAILED, RunState.STOPPED},
    RunState.REVIEWING: {RunState.COMPLETED, RunState.FAILED, RunState.STOPPED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.STOPPED: set(),
}


@dataclass
class AgentRun:
    run_id: str
    state: RunState = RunState.IDLE
    stop_event: Event = field(default_factory=Event)

    def transition(self, target: RunState) -> RunState:
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"Invalid transition: {self.state} -> {target}")
        self.state = target
        return self.state

    def stop(self) -> None:
        self.stop_event.set()
        if self.state not in {RunState.COMPLETED, RunState.FAILED, RunState.STOPPED}:
            self.state = RunState.STOPPED

    def ensure_active(self) -> None:
        if self.stop_event.is_set():
            self.state = RunState.STOPPED
            raise RuntimeError("Agent execution was stopped by the user")
