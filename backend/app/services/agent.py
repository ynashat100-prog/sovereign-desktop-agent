"""Agent orchestrator: model output is advisory; tools are parsed and executed only by policy."""

from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

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

_SYSTEM_PROMPT = """You are a private desktop assistant. You must never claim that you executed a system action.
When a listed tool is useful, respond with exactly one line in this format:
TOOL: tool.name | {"argument":"value"} | short rationale
Available tools: system.active_context, application.list, application.open, filesystem.read_text,
filesystem.search, filesystem.write_text, filesystem.create_file, filesystem.create_folder,
filesystem.open, filesystem.delete, clipboard.read, clipboard.write, system.screenshot,
system.volume, system.brightness, system.open_settings, web.search, terminal.run.
Never request or invent a tool outside this list. The permission engine—not you—decides whether
an action runs. For ordinary questions, respond normally and concisely."""


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
                direct_tool = self._deterministic_tool(request.text)
                if direct_tool and self.permissions.requires_approval(direct_tool, request.session_id):
                    run.transition(RunState.PLANNING)
                    run.transition(RunState.AWAITING_PERMISSION)
                    self.permissions.request(run_id, request.session_id, direct_tool)
                    await self._trace(
                        request,
                        run_id,
                        "permission",
                        "Permission confirmation required",
                        tool=direct_tool.name,
                    )
                    return self._response(
                        run,
                        request,
                        run_id,
                        f"Permission required for {direct_tool.name}. Review the requested action in the UI.",
                        started,
                        [direct_tool],
                    )
                run.transition(RunState.EXECUTING)
                result = await self._fast_task(request.text, request, run_id, direct_tool)
                run.transition(RunState.COMPLETED)
                return self._response(
                    run, request, run_id, result, started, [direct_tool] if direct_tool else None
                )

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
                if self.permissions.requires_approval(tool_call, request.session_id):
                    run.transition(RunState.AWAITING_PERMISSION)
                    self.permissions.request(run_id, request.session_id, tool_call)
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
        finally:
            if run.state != RunState.AWAITING_PERMISSION:
                self.runs.pop(run_id, None)

    async def approve(self, run_id: str, decision: str, request: MessageRequest) -> AgentResponse:
        started = perf_counter()
        run = self.runs.get(run_id)
        if not run:
            raise KeyError("Unknown run")
        try:
            tool = self.permissions.decide(run_id, request.session_id, decision)
            run.ensure_active()
            run.transition(RunState.EXECUTING)
            result = await self._execute_tool(tool, request, run_id, run)
            run.transition(RunState.COMPLETED)
            return self._response(run, request, run_id, result, started, [tool])
        except PermissionError:
            run.state = RunState.FAILED
            raise
        finally:
            if run.state != RunState.AWAITING_PERMISSION:
                self.runs.pop(run_id, None)

    def stop(self, run_id: str | None = None) -> int:
        targets = [self.runs[run_id]] if run_id and run_id in self.runs else ([] if run_id else list(self.runs.values()))
        count = 0
        for run in targets:
            if run.state not in {RunState.COMPLETED, RunState.FAILED, RunState.STOPPED}:
                run.stop()
                count += 1
        self.permissions.clear(run_id)
        return count

    async def _fast_task(
        self,
        text: str,
        request: MessageRequest,
        run_id: str,
        direct_tool: ToolCall | None = None,
    ) -> str:
        lowered = text.lower()
        if "time" in lowered or "الوقت" in lowered:
            from datetime import datetime

            return f"Local time: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
        if direct_tool:
            return await self._execute_tool(direct_tool, request, run_id, self.runs[run_id])
        return "I recognized a local request, but I need a more specific file path, query, or action."

    @staticmethod
    def _tool_call(name: str, arguments: dict[str, object], rationale: str) -> ToolCall:
        return ToolCall(
            name=name,
            arguments=arguments,
            permission=TOOLS[name].permission,
            rationale=rationale,
        )

    def _deterministic_tool(self, text: str) -> ToolCall | None:
        """Map conservative, explicit requests to allow-listed local actions.

        This gives core desktop tasks a reliable path even when a local model is unavailable.
        Broad or ambiguous requests intentionally return ``None`` and remain model-mediated.
        """
        lowered = text.lower().strip()

        if any(term in lowered for term in ("التطبيقات المثبتة", "البرامج المثبتة", "installed apps")):
            return self._tool_call("application.list", {}, "Requested installed application list")
        if any(term in lowered for term in ("العمليات", "البرامج النشطة", "active processes")):
            return self._tool_call("system.active_context", {}, "Requested local process context")
        if any(term in lowered for term in ("لقطة شاشة", "صورة للشاشة", "screenshot")):
            return self._tool_call("system.screenshot", {}, "Requested a local screenshot")

        search_match = re.search(
            r"(?:ابحث(?: على الإنترنت)? عن|search (?:the )?web for|web search)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if search_match:
            return self._tool_call(
                "web.search",
                {"query": search_match.group(1).strip()},
                "Requested public web search",
            )

        brightness_match = re.search(r"(?:السطوع|brightness).*?(\d{1,3})", lowered)
        if brightness_match:
            return self._tool_call(
                "system.brightness",
                {"level": int(brightness_match.group(1))},
                "Requested display brightness change",
            )
        if any(term in lowered for term in ("ارفع الصوت", "زود الصوت", "volume up")):
            return self._tool_call("system.volume", {"action": "up"}, "Requested volume increase")
        if any(term in lowered for term in ("اخفض الصوت", "قلل الصوت", "volume down")):
            return self._tool_call("system.volume", {"action": "down"}, "Requested volume decrease")
        if any(term in lowered for term in ("اكتم الصوت", "كتم الصوت", "mute")):
            return self._tool_call("system.volume", {"action": "mute"}, "Requested volume mute")

        settings_pages = {
            "الشاشة": "display",
            "العرض": "display",
            "display settings": "display",
            "الصوت": "sound",
            "sound settings": "sound",
            "البلوتوث": "bluetooth",
            "bluetooth": "bluetooth",
            "الشبكة": "network",
            "network settings": "network",
            "الخصوصية": "privacy",
            "privacy settings": "privacy",
        }
        if "إعدادات" in text or "settings" in lowered:
            for term, page in settings_pages.items():
                if term in lowered:
                    return self._tool_call(
                        "system.open_settings", {"page": page}, "Requested Windows Settings page"
                    )

        folder_match = re.search(
            r"(?:أنشئ|انشئ|create)\s+(?:مجلد|folder)\s+(.+)$", text, re.IGNORECASE
        )
        if folder_match:
            return self._tool_call(
                "filesystem.create_folder",
                {"path": folder_match.group(1).strip(" '\"“”")},
                "Requested new folder",
            )

        file_search = re.search(
            r"(?:ابحث عن ملف|search (?:for )?file)\s+(.+)$", text, re.IGNORECASE
        )
        if file_search:
            query = file_search.group(1).strip(" '\"“”")
            return self._tool_call(
                "filesystem.search",
                {"pattern": f"*{query}*"},
                "Requested local file search",
            )

        read_match = re.search(r"(?:اقرأ ملف|read file)\s+(.+)$", text, re.IGNORECASE)
        if read_match:
            return self._tool_call(
                "filesystem.read_text",
                {"path": read_match.group(1).strip(" '\"“”")},
                "Requested text file read",
            )

        open_path_match = re.search(
            r"(?:افتح (?:الملف|المجلد)|open (?:file|folder))\s+(.+)$", text, re.IGNORECASE
        )
        if open_path_match:
            return self._tool_call(
                "filesystem.open",
                {"path": open_path_match.group(1).strip(" '\"“”")},
                "Requested local file or folder open",
            )

        app_match = re.search(r"(?:افتح برنامج|open app)\s+([\w.-]+)$", text, re.IGNORECASE)
        if app_match:
            return self._tool_call(
                "application.open",
                {"executable": app_match.group(1)},
                "Requested application start",
            )

        delete_match = re.search(
            r"(?:احذف (?:ملف|مجلد)|delete (?:file|folder))\s+(.+)$", text, re.IGNORECASE
        )
        if delete_match:
            path = delete_match.group(1).strip(" '\"“”")
            recursive = any(term in lowered for term in ("بكل محتوياته", "recursively"))
            return self._tool_call(
                "filesystem.delete",
                {"path": path, "recursive": recursive},
                "Requested permanent deletion",
            )

        if any(term in lowered for term in ("اقرأ الحافظة", "محتوى الحافظة", "read clipboard")):
            return self._tool_call("clipboard.read", {}, "Requested clipboard contents")
        return None

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
        result = await run_in_threadpool(registered.handler, tool.arguments)
        await self._trace(request, run_id, "result", "Tool completed", tool=tool.name)
        return f"{tool.name} completed: {result}"

    def _parse_tool(self, text: str) -> ToolCall | None:
        match = re.match(
            r"^TOOL:\s*([\w.]+)\s*\|\s*(\{.*\})\s*\|\s*(.+)$", text.strip(), re.DOTALL
        )
        if not match:
            return None
        import json

        name, raw_args, rationale = match.groups()
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool JSON: {exc.msg}") from exc
        if name not in TOOLS:
            raise ValueError(f"Tool is not allow-listed: {name}")
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
