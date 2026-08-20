"""FastAPI entry point. The Tauri shell launches this runtime as a managed sidecar."""

from __future__ import annotations

import asyncio
import json
import platform
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.models.schemas import (
    MessageRequest,
    OllamaPullRequest,
    PermissionDecision,
    ProviderStatus,
    ProviderUpsertRequest,
    RuntimeStatus,
    SetupCheck,
    SetupReport,
    TraceEvent,
)
from app.providers.cloud import (
    GroqProvider,
    MistralProvider,
    NvidiaProvider,
    OpenAICompatibleProvider,
)
from app.providers.ollama import OllamaProvider
from app.services.agent import AgentService
from app.services.permissions import PermissionManager
from app.services.provider_registry import ProviderRegistry
from app.services.router import SmartRouter
from app.services.traces import trace_hub

ollama_provider = OllamaProvider(settings)
providers = [
    ollama_provider,
    NvidiaProvider(settings.nvidia_api_key, settings.nvidia_model),
    MistralProvider(settings.mistral_api_key, settings.mistral_model),
    GroqProvider(settings.groq_api_key, settings.groq_model),
]
provider_registry = ProviderRegistry(settings.agent_data_dir / "providers.json")
agent = AgentService(settings, providers, SmartRouter(), PermissionManager(), trace_hub)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.agent_data_dir.mkdir(parents=True, exist_ok=True)
    yield
    agent.stop()


app = FastAPI(title="Sovereign Desktop Agent Runtime", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _custom_statuses() -> list[ProviderStatus]:
    return [
        ProviderStatus(
            id=item["id"],
            name=item["name"],
            kind="cloud",
            available=bool(item["api_key_masked"]),
            detail="Configured securely; explicit Hybrid consent required"
            if item["api_key_masked"]
            else "API key not configured",
            models=[item["model"]],
        )
        for item in provider_registry.list()
    ]


def _bind_custom_provider(provider_id: str) -> None:
    record = provider_registry.provider(provider_id)
    api_key = provider_registry.secret(provider_id)
    if not record or not api_key:
        raise ValueError("Configured provider or secure API key not found")
    agent.providers[provider_id] = OpenAICompatibleProvider(
        provider_id=record.id,
        name=record.name,
        api_key=api_key,
        base_url=record.base_url,
        model=record.model,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sovereign-desktop-agent-runtime"}


@app.get("/v1/status", response_model=RuntimeStatus)
async def runtime_status() -> RuntimeStatus:
    statuses = await asyncio.gather(*(provider.status() for provider in agent.providers.values()))
    ollama = next(item for item in statuses if item.id == "ollama")
    clouds = [item for item in statuses if item.id != "ollama"] + _custom_statuses()
    return RuntimeStatus(
        runtime_available=True, demo_mode=settings.agent_demo_mode, ollama=ollama, cloud=clouds
    )


@app.get("/v1/setup", response_model=SetupReport)
async def setup_report() -> SetupReport:
    status = await runtime_status()
    checks = [
        SetupCheck(
            key="os",
            label="Operating system",
            status="ready",
            detail=f"{platform.system()} {platform.release()}",
        ),
        SetupCheck(
            key="runtime",
            label="Desktop runtime",
            status="ready",
            detail="FastAPI sidecar is running",
        ),
        SetupCheck(
            key="ollama",
            label="Ollama",
            status="ready" if status.ollama.available else "warning",
            detail=status.ollama.detail,
        ),
        SetupCheck(
            key="cloud",
            label="Cloud fallback",
            status="ready" if any(item.available for item in status.cloud) else "warning",
            detail="Optional and never automatic in Local Only mode",
        ),
        SetupCheck(
            key="vision",
            label="Vision",
            status="warning",
            detail="On-demand only; configure a supported model to enable",
        ),
    ]
    recommendations = []
    if not status.ollama.available:
        recommendations.append(
            "Install and start Ollama, then pull qwen2.5-coder:7b for local-first operation."
        )
    if not any(item.available for item in status.cloud):
        recommendations.append("Demo Mode remains available without cloud API keys.")
    return SetupReport(checks=checks, recommendations=recommendations)


@app.get("/v1/providers")
async def list_providers():
    return {"providers": provider_registry.list()}


@app.post("/v1/providers")
async def save_provider(request: ProviderUpsertRequest):
    try:
        return provider_registry.upsert(
            record_id=request.id,
            name=request.name,
            base_url=request.base_url,
            model=request.model,
            api_key=request.api_key,
            fallback_enabled=request.fallback_enabled,
            preset=request.preset,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v1/providers/{provider_id}")
async def delete_provider(provider_id: str):
    if not provider_registry.delete(provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    agent.providers.pop(provider_id, None)
    return {"deleted": True}


@app.post("/v1/providers/{provider_id}/test")
async def test_provider(provider_id: str):
    try:
        return await provider_registry.test(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/models/pull")
async def pull_model(request: OllamaPullRequest, session_id: str):
    run_id = f"model:{uuid4()}"

    async def stream():
        try:
            async for event in ollama_provider.pull(request.model):
                await trace_hub.publish(
                    session_id,
                    TraceEvent(
                        run_id=run_id,
                        category="provider",
                        message=f"Ollama pull: {event.get('status', 'working')}",
                        metadata=event,
                    ),
                )
                yield json.dumps(event) + "\n"
        except Exception as exc:
            error = {"status": "error", "detail": str(exc)}
            await trace_hub.publish(
                session_id,
                TraceEvent(run_id=run_id, category="error", message=f"Ollama pull failed: {exc}"),
            )
            yield json.dumps(error) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/v1/messages")
async def submit_message(request: MessageRequest):
    if request.selected_provider and request.selected_provider != "ollama":
        if request.privacy_mode != "hybrid" or not request.cloud_consent:
            raise HTTPException(
                status_code=409,
                detail="Cloud provider requires Hybrid mode and explicit consent for this request",
            )
        if request.selected_provider not in agent.providers:
            try:
                _bind_custom_provider(request.selected_provider)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await agent.run(request)


@app.post("/v1/permissions")
async def decide_permission(decision: PermissionDecision):
    try:
        return await agent.approve(
            decision.run_id,
            decision.decision,
            MessageRequest(text="Permission decision", session_id="permissions"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/v1/stop")
async def stop_agent(run_id: str | None = None):
    return {"stopped_runs": agent.stop(run_id)}


@app.websocket("/v1/ws/{session_id}")
async def trace_socket(websocket: WebSocket, session_id: str):
    await trace_hub.connect(session_id, websocket)
    try:
        await trace_hub.wait_for_disconnect(websocket)
    finally:
        trace_hub.disconnect(session_id, websocket)
