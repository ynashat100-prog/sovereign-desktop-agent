import { useCallback, useEffect, useMemo, useState } from "react";
import type { AgentResponse, CustomProvider, RuntimeStatus, SetupReport, TraceEvent } from "../types/runtime";

const API_URL = import.meta.env.VITE_RUNTIME_URL ?? "http://127.0.0.1:8765";

export function useRuntime(sessionId: string) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [traces, setTraces] = useState<TraceEvent[]>([]);
  const [setup, setSetup] = useState<SetupReport | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/v1/status`);
      if (!response.ok) throw new Error("Runtime status unavailable");
      setStatus((await response.json()) as RuntimeStatus);
      const setupResponse = await fetch(`${API_URL}/v1/setup`);
      if (setupResponse.ok) setSetup((await setupResponse.json()) as SetupReport);
      setError(null);
    } catch {
      setError("Runtime unavailable. You can still explore Demo Mode.");
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const socketUrl = API_URL.replace(/^http/, "ws") + `/v1/ws/${sessionId}`;
    const socket = new WebSocket(socketUrl);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (event) => {
      const trace = JSON.parse(event.data) as TraceEvent;
      setTraces((previous) => [...previous.slice(-199), trace]);
    };
    return () => socket.close();
  }, [refreshStatus, sessionId]);

  const submit = useCallback(
    async (text: string, options: { demoMode: boolean; selectedProvider?: string; privacyMode: "local_only" | "hybrid"; cloudConsent?: boolean; allowScreenshot?: boolean }) => {
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

  const pullModel = useCallback(async (model: string) => {
    const response = await fetch(`${API_URL}/v1/models/pull?session_id=${encodeURIComponent(sessionId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
    if (!response.ok || !response.body) throw new Error("Model download could not start");
    const reader = response.body.getReader();
    while (true) { const { done } = await reader.read(); if (done) break; }
  }, [sessionId]);

  return useMemo(
    () => ({ status, setup, traces, connected, error, refreshStatus, submit, stop, listProviders, saveProvider, deleteProvider, testProvider, pullModel, clearTraces: () => setTraces([]) }),
    [status, setup, traces, connected, error, refreshStatus, submit, stop, listProviders, saveProvider, deleteProvider, testProvider, pullModel],
  );
}
