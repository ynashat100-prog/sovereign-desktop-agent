import { useCallback, useEffect, useMemo, useState } from "react";
import type { AgentResponse, CustomProvider, RuntimeStatus, SetupReport, TraceEvent } from "../types/runtime";

const API_URL = import.meta.env.VITE_RUNTIME_URL ?? "http://127.0.0.1:8765";
const RETRY_DELAY_MS = 1500;
const STATUS_REFRESH_MS = 5000;

export function useRuntime(sessionId: string) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [traces, setTraces] = useState<TraceEvent[]>([]);
  const [setup, setSetup] = useState<SetupReport | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dangerousToolsEnabled, setDangerousToolsEnabled] = useState(false);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/v1/status`);
      if (!response.ok) throw new Error("Runtime status unavailable");
      setStatus((await response.json()) as RuntimeStatus);
      const setupResponse = await fetch(`${API_URL}/v1/setup`);
      if (setupResponse.ok) setSetup((await setupResponse.json()) as SetupReport);
      const permissionsResponse = await fetch(`${API_URL}/v1/permissions/settings`);
      if (permissionsResponse.ok) setDangerousToolsEnabled(((await permissionsResponse.json()) as { enabled: boolean }).enabled);
      setError(null);
      return true;
    } catch {
      setStatus(null);
      setSetup(null);
      setDangerousToolsEnabled(false);
      setError("Runtime unavailable. Retrying connection automatically.");
      return false;
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;

    const scheduleRetry = () => {
      if (!disposed) retryTimer = window.setTimeout(connect, RETRY_DELAY_MS);
    };

    const connect = () => {
      if (disposed) return;
      void refreshStatus();
      const socketUrl = API_URL.replace(/^http/, "ws") + `/v1/ws/${sessionId}`;
      socket = new WebSocket(socketUrl);
      socket.onopen = () => {
        if (!disposed) setConnected(true);
      };
      socket.onclose = () => {
        if (!disposed) {
          setConnected(false);
          scheduleRetry();
        }
      };
      socket.onerror = () => {
        if (!disposed) setConnected(false);
      };
      socket.onmessage = (event) => {
        const trace = JSON.parse(event.data) as TraceEvent;
        setTraces((previous) => [...previous.slice(-199), trace]);
      };
    };

    connect();
    const statusTimer = window.setInterval(() => void refreshStatus(), STATUS_REFRESH_MS);
    return () => {
      disposed = true;
      window.clearInterval(statusTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [refreshStatus, sessionId]);

  const submit = useCallback(
    async (
      text: string,
      options: {
        demoMode: boolean;
        selectedProvider?: string;
        privacyMode: "local_only" | "hybrid";
        cloudConsent?: boolean;
        allowScreenshot?: boolean;
      },
    ) => {
      const response = await fetch(`${API_URL}/v1/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          session_id: sessionId,
          demo_mode: options.demoMode,
          selected_provider: options.selectedProvider,
          privacy_mode: options.privacyMode,
          cloud_consent: options.cloudConsent ?? false,
          allow_screenshot: options.allowScreenshot ?? false,
        }),
      });
      if (!response.ok) throw new Error("Agent request failed");
      return (await response.json()) as AgentResponse;
    },
    [sessionId],
  );

  const stop = useCallback(async () => {
    await fetch(`${API_URL}/v1/stop`, { method: "POST" });
  }, []);

  const decidePermission = useCallback(async (runId: string, decision: "allow_once" | "allow_always" | "deny") => {
    const response = await fetch(`${API_URL}/v1/permissions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: runId, decision }) });
    if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Permission decision failed");
    return (await response.json()) as AgentResponse;
  }, []);

  const setDangerousTools = useCallback(async (enabled: boolean) => {
    const response = await fetch(`${API_URL}/v1/permissions/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
    if (!response.ok) throw new Error("Permission settings could not be changed");
    const result = (await response.json()) as { enabled: boolean };
    setDangerousToolsEnabled(result.enabled);
  }, []);

  const listProviders = useCallback(async () => {
    const response = await fetch(`${API_URL}/v1/providers`);
    if (!response.ok) throw new Error("Provider list unavailable");
    return ((await response.json()) as { providers: CustomProvider[] }).providers;
  }, []);

  const saveProvider = useCallback(async (provider: Omit<CustomProvider, "id" | "api_key_masked"> & { id?: string; api_key?: string }) => {
    const response = await fetch(`${API_URL}/v1/providers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(provider) });
    if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Provider could not be saved");
    return (await response.json()) as CustomProvider;
  }, []);

  const deleteProvider = useCallback(async (id: string) => {
    const response = await fetch(`${API_URL}/v1/providers/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Provider could not be deleted");
  }, []);

  const testProvider = useCallback(async (id: string) => {
    const response = await fetch(`${API_URL}/v1/providers/${id}/test`, { method: "POST" });
    if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Connection test failed");
    return (await response.json()) as { ok: boolean; status_code: number };
  }, []);

  const discoverProviderModels = useCallback(async (baseUrl: string, apiKey: string) => {
    const response = await fetch(`${API_URL}/v1/providers/discover-models`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }) });
    if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Model discovery failed");
    return (await response.json() as { models: string[] }).models;
  }, []);

  const setActiveModel = useCallback(async (model: string) => {
    const response = await fetch(`${API_URL}/v1/models/active`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
    if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Model selection failed");
    await refreshStatus();
  }, [refreshStatus]);

  const pullModel = useCallback(async (model: string) => {
    const response = await fetch(`${API_URL}/v1/models/pull?session_id=${encodeURIComponent(sessionId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
    if (!response.ok || !response.body) throw new Error("Model download could not start");
    const reader = response.body.getReader();
    let failure: string | undefined;
    const decoder = new window.TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of decoder.decode(value, { stream: true }).split("\n")) {
        if (!line) continue;
        const event = JSON.parse(line) as { status?: string; detail?: string };
        if (event.status === "error") failure = event.detail ?? "Model download failed";
      }
    }
    if (failure) throw new Error(failure);
    await refreshStatus();
  }, [refreshStatus, sessionId]);

  return useMemo(
    () => ({ status, setup, traces, connected, error, dangerousToolsEnabled, refreshStatus, submit, stop, decidePermission, setDangerousTools, listProviders, saveProvider, deleteProvider, testProvider, discoverProviderModels, setActiveModel, pullModel, clearTraces: () => setTraces([]) }),
    [status, setup, traces, connected, error, dangerousToolsEnabled, refreshStatus, submit, stop, decidePermission, setDangerousTools, listProviders, saveProvider, deleteProvider, testProvider, discoverProviderModels, setActiveModel, pullModel],
  );
}
