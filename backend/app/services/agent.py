"""Agent orchestrator: model output is advisory; tools are parsed and executed only by policy."""

from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

from app.core.config import Settings
from app.core.state_machine import AgentRun
from app.models.schemas import (
    AgentResponse,
    MessageRequest,
    RunState,
    ToolCall,
    TraceEvent,
)
from app.providers.base import ModelProvider
from app.services.permissions import PermissionManager
from app.services.router import SmartRouter
from app.services.traces import TraceHub
from app.tools.catalog import TOOLS

_SYSTEM_PROMPT = """You are a desktop assistant. You must never claim that you executed a system action.
When a tool is useful, respond with exactly one line in this format:
TOOL: tool.name | {"argument":"value"} | short rationale
Available tools: system.active_context, filesystem.read_text, filesystem.search,
filesystem.create_file, filesystem.create_folder, filesystem.open, application.open,
clipboard.read, clipboard.write, terminal.run.
All write actions require confirmation. For ordinary questions, respond normally and concisely."""


class AgentService:
    def __init__(
        self,
        settings: Settings,
        providers: list[ModelProvider],
        router: SmartRouter,
        permissions: PermissionManager,
        traces: TraceHub,
    ) -> None:
        self.settings = settings
        self.providers = {provider.id: provider for provider in providers}
        self.router = router
        self.permissions = permissions
        self.traces = traces
        self.runs: dict[str, AgentRun] = {}

    async def _trace(
        self, request: MessageRequest, run_id: str, category: str, message: str, **metadata
    ) -> None:
        await self.traces.publish(
            request.session_id,
            TraceEvent(run_id=run_id, category=category, message=message, metadata=metadata),
        )

    async def run(self, request: MessageRequest) -> AgentResponse:
        started = perf_counter()
        run_id = str(uuid4())
        run = AgentRun(run_id)
        self.runs[run_id] = run
        try:
            await self._trace(request, run_id, "request", "Request received")
            run.transition(RunState.ROUTING)
            route = await self.router.route(
                request.text,
                list(self.providers.values()),
                request.selected_provider,
                allow_cloud=request.privacy_mode == "hybrid" and request.cloud_consent,
            )
            await self._trace(
                request, run_id, "router", f"Router → {route.mode}", reason=route.reason
            )
            run.ensure_active()

            if route.mode == "fast":
                run.transition(RunState.EXECUTING)
                result = await self._fast_task(request.text, request, run_id)
                run.transition(RunState.COMPLETED)
                return self._response(run, request, run_id, result, started)

            if route.mode == "demo" or request.demo_mode or self.settings.agent_demo_mode:
                run.transition(RunState.PLANNING)
                await self._trace(request, run_id, "provider", "Demo Mode → simulated local model")
                run.transition(RunState.REVIEWING)
                await self._trace(request, run_id, "result", "Demo response generated")
                run.transition(RunState.COMPLETED)
                return self._response(
                    run,
                    request,
                    run_id,
                    "Demo Mode is active. Configure Ollama or an optional cloud provider for live generation.",
                    started,
                )

            run.transition(RunState.PLANNING)
            provider = self.providers[route.provider_id or "ollama"]
            await self._trace(
                request,
                run_id,
                "provider",
                f"Model → {provider.name}",
                local=route.provider_id == "ollama",
            )
            generation = await provider.generate(request.text, system=_SYSTEM_PROMPT)
            run.ensure_active()
            tool_call = self._parse_tool(generation.text)
            if tool_call:
                if self.permissions.requires_approval(tool_call):
                    run.transition(RunState.AWAITING_PERMISSION)
                    self.permissions.request(run_id, tool_call)
                    await self._trace(
                        request,
                        run_id,
                        "permission",
                        "Permission confirmation required",
                        tool=tool_call.name,
                    )
                    return self._response(
                        run,
                        request,
                        run_id,
                        f"Permission required for {tool_call.name}. Review the requested action in the UI.",
                        started,
                        [tool_call],
                    )
                run.transition(RunState.EXECUTING)
                result = await self._execute_tool(tool_call, request, run_id, run)
                run.transition(RunState.COMPLETED)
                return self._response(run, request, run_id, result, started, [tool_call])

            run.transition(RunState.REVIEWING)
            await self._trace(
                request,
                run_id,
                "result",
                "Response generated",
                provider=generation.provider,
                model=generation.model,
            )
            run.transition(RunState.COMPLETED)
            return self._response(run, request, run_id, generation.text, started)
        except Exception as exc:
            if run.state != RunState.STOPPED:
                run.state = RunState.FAILED
            await self._trace(request, run_id, "error", f"Runtime error: {exc}")
            return self._response(run, request, run_id, f"Feature unavailable: {exc}", started)

    async def approve(self, run_id: str, decision: str, request: MessageRequest) -> AgentResponse:
        started = perf_counter()
        run = self.runs.get(run_id)
        if not run:
            raise KeyError("Unknown run")
        tool = self.permissions.decide(run_id, decision)
        run.ensure_active()
        run.transition(RunState.EXECUTING)
        result = await self._execute_tool(tool, request, run_id, run)
        run.transition(RunState.COMPLETED)
        return self._response(run, request, run_id, result, started, [tool])

    def stop(self, run_id: str | None = None) -> int:
        targets = [self.runs[run_id]] if run_id and run_id in self.runs else self.runs.values()
        count = 0
        for run in targets:
            if run.state not in {RunState.COMPLETED, RunState.FAILED, RunState.STOPPED}:
                run.stop()
                count += 1
        self.permissions.clear()
        return count

    async def _fast_task(self, text: str, request: MessageRequest, run_id: str) -> str:
        lowered = text.lower()
        if "time" in lowered or "الوقت" in lowered:
            from datetime import datetime

            return f"Local time: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
        if any(word in lowered for word in ("process", "التطبيق", "النشط")):
            tool = ToolCall(
                name="system.active_context",
                arguments={},
                permission=TOOLS["system.active_context"].permission,
                rationale="Requested local process context",
            )
            return await self._execute_tool(tool, request, run_id, self.runs[run_id])
        return "I recognized a simple request, but it does not match an enabled deterministic tool yet."

    async def _execute_tool(
        self, tool: ToolCall, request: MessageRequest, run_id: str, run: AgentRun
    ) -> str:
        run.ensure_active()
        registered = TOOLS.get(tool.name)
        if not registered:
            raise ValueError(f"Tool is not allow-listed: {tool.name}")
        await self._trace(
            request, run_id, "tool", f"Tool → {tool.name}", permission=tool.permission.value
        )
        result = registered.handler(tool.arguments)
        await self._trace(request, run_id, "result", "Tool completed", tool=tool.name)
        return f"{tool.name} completed: {result}"

    def _parse_tool(self, text: str) -> ToolCall | None:
        match = re.match(
            r"^TOOL:\\s*([\\w.]+)\\s*\\|\\s*(\\{.*\\})\\s*\\|\\s*(.+)$", text.strip(), re.DOTALL
        )
        if not match:
            return None
        import json

        name, raw_args, rationale = match.groups()
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool JSON: {exc.msg}") from exc
        permission = self.permissions.permission_for(name, arguments)
        return ToolCall(name=name, arguments=arguments, permission=permission, rationale=rationale)

    @staticmethod
    def _response(
        run: AgentRun,
        request: MessageRequest,
        run_id: str,
        message: str,
        started: float,
        tools: list[ToolCall] | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            run_id=run_id,
            session_id=request.session_id,
            state=run.state,
            message=message,
            tool_calls=tools or [],
            latency_ms=round((perf_counter() - started) * 1000),
        )
