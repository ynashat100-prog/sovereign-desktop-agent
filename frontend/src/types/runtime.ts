export type Locale = "ar" | "en";
export type PrivacyMode = "local" | "hybrid";

export interface TraceEvent {
  id: string;
  run_id: string;
  timestamp: string;
  category: "request" | "router" | "provider" | "tool" | "permission" | "state" | "result" | "error";
  message: string;
  metadata: Record<string, unknown>;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  permission: "safe" | "confirm" | "dangerous";
  rationale: string;
}

export interface AgentResponse {
  run_id: string;
  session_id: string;
  state: string;
  message: string;
  tool_calls: ToolCall[];
  latency_ms: number;
}

export interface ProviderStatus {
  id: string;
  name: string;
  kind: "local" | "cloud" | "vision";
  available: boolean;
  detail: string;
  models: string[];
}

export interface RuntimeStatus {
  runtime_available: boolean;
  demo_mode: boolean;
  ollama: ProviderStatus;
  cloud: ProviderStatus[];
  vision: ProviderStatus[];
}

export interface SetupCheck {
  key: string;
  label: string;
  status: "ready" | "warning" | "unavailable";
  detail: string;
}

export interface SetupReport {
  checks: SetupCheck[];
  recommendations: string[];
}

export interface CustomProvider {
  id: string;
  name: string;
  base_url: string;
  model: string;
  fallback_enabled: boolean;
  preset?: string | null;
  api_key_masked?: string | null;
}
