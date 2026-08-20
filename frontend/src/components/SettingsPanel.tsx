import { useCallback, useEffect, useState } from "react";
import { Check, Download, KeyRound, ListRestart, Plus, Save, ShieldCheck, Trash2, Wifi } from "lucide-react";
import { translate } from "../i18n";
import type { CustomProvider, Locale, RuntimeStatus } from "../types/runtime";

interface ProviderDraft {
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  fallback_enabled: boolean;
  preset?: string;
}

interface Props {
  locale: Locale;
  status: RuntimeStatus | null;
  listProviders: () => Promise<CustomProvider[]>;
  saveProvider: (provider: ProviderDraft) => Promise<CustomProvider>;
  deleteProvider: (id: string) => Promise<void>;
  testProvider: (id: string) => Promise<{ ok: boolean; status_code: number }>;
  discoverProviderModels: (baseUrl: string, apiKey: string) => Promise<string[]>;
  pullModel: (model: string) => Promise<void>;
  setActiveModel: (model: string) => Promise<void>;
  dangerousToolsEnabled: boolean;
  setDangerousTools: (enabled: boolean) => Promise<void>;
  selectedProvider?: string;
  onSelectProvider: (provider?: CustomProvider) => void;
}

const recommended = ["qwen2.5-coder:7b", "qwen2.5-coder:14b"];
const blankDraft: ProviderDraft = { name: "", base_url: "", api_key: "", model: "", fallback_enabled: false };
const presets = [
  { name: "NVIDIA NIM", base_url: "https://integrate.api.nvidia.com/v1", model: "meta/llama-3.1-70b-instruct", preset: "nvidia" },
  { name: "Mistral", base_url: "https://api.mistral.ai/v1", model: "mistral-small-latest", preset: "mistral" },
  { name: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama-3.1-8b-instant", preset: "groq" },
  { name: "xAI (Grok)", base_url: "https://api.x.ai/v1", model: "grok-4.6", preset: "xai" },
];

export function SettingsPanel({ locale, status, listProviders, saveProvider, deleteProvider, testProvider, discoverProviderModels, pullModel, setActiveModel, dangerousToolsEnabled, setDangerousTools, selectedProvider, onSelectProvider }: Props) {
  const [providers, setProviders] = useState<CustomProvider[]>([]);
  const [draft, setDraft] = useState<ProviderDraft>(blankDraft);
  const [customModel, setCustomModel] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  const refreshProviders = useCallback(async () => {
    try { setProviders(await listProviders()); } catch { setProviders([]); }
  }, [listProviders]);

  useEffect(() => { void refreshProviders(); }, [refreshProviders]);

  const displayError = (error: unknown) => {
    const message = error instanceof Error ? error.message : "";
    if (message.includes("Secure credential")) return t("secureStorageUnavailable");
    if (message.includes("Application data")) return t("appStorageUnavailable");
    if (message.includes("HTTP")) return `${t("providerRejected")}: ${message}`;
    return message || t("unavailable");
  };

  const download = async (model: string) => {
    if (!status?.ollama.available) { setNotice(t("ollamaRequired")); return; }
    if (!window.confirm(t("downloadConfirm"))) return;
    setBusyAction(`download:${model}`);
    try {
      await pullModel(model);
      setNotice(t("downloadCompleted"));
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const activateModel = async (model: string) => {
    if (!status?.ollama.available) { setNotice(t("ollamaRequired")); return; }
    setBusyAction(`select:${model}`);
    try {
      await setActiveModel(model);
      setNotice(t("modelSelected"));
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const discoverModels = async () => {
    if (!draft.base_url || !draft.api_key) { setNotice(t("keyOptional")); return; }
    setBusyAction("discover");
    try {
      const models = await discoverProviderModels(draft.base_url, draft.api_key);
      setDiscoveredModels(models);
      setDraft((current) => ({ ...current, model: current.model || models[0] || "" }));
      setNotice(t("modelsDiscovered"));
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const save = async () => {
    setBusyAction("save");
    try {
      const provider = await saveProvider(draft);
      setDraft(blankDraft);
      setDiscoveredModels([]);
      setNotice(t("providerSaved"));
      onSelectProvider(provider);
      await refreshProviders();
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const toggleDangerousTools = async (enabled: boolean) => {
    if (enabled && !window.confirm(t("dangerousToolsDescription"))) return;
    setBusyAction("dangerous-tools");
    try {
      await setDangerousTools(enabled);
      setNotice(enabled ? t("dangerousToolsEnabled") : t("ready"));
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const test = async (provider: CustomProvider) => {
    setBusyAction(`test:${provider.id}`);
    try {
      const result = await testProvider(provider.id);
      setNotice(result.ok ? t("ready") : `${t("providerRejected")}: HTTP ${result.status_code}`);
    } catch (error) {
      setNotice(displayError(error));
    } finally {
      setBusyAction(null);
    }
  };

  const installedModels = status?.ollama.models ?? [];
  const activeModel = installedModels[0];

  return (
    <aside className="settings-panel" aria-label={t("settings")}>
      <div className="panel-heading"><div><p className="eyebrow">{t("settings")}</p><h2>{t("modelManagement")}</h2></div><ShieldCheck size={21} /></div>
      {!status?.ollama.available && <p className="settings-warning">{t("ollamaRequired")}</p>}
      <div className="model-grid">
        {recommended.map((model) => {
          const installed = installedModels.includes(model);
          const active = model === activeModel;
          return <article className="model-card" key={model}><strong>{model}</strong><span className={installed ? "good" : "muted"}>{active ? t("activeModel") : installed ? t("installed") : t("notInstalled")}</span>{installed ? <button className={active ? "secondary active-model" : "secondary"} disabled={active || busyAction === `select:${model}`} onClick={() => void activateModel(model)}><Check size={15} /> {active ? t("activeModel") : t("useModel")}</button> : <button className="secondary" disabled={!status?.ollama.available || busyAction === `download:${model}`} onClick={() => void download(model)}><Download size={15} /> {t("downloadModel")}</button>}</article>;
        })}
      </div>
      <div className="custom-model"><label>{t("customModel")}</label><div><input value={customModel} onChange={(event) => setCustomModel(event.target.value)} placeholder="qwen2.5-coder:7b" />{installedModels.includes(customModel) ? <button className="secondary" disabled={customModel === activeModel || busyAction === `select:${customModel}`} onClick={() => void activateModel(customModel)}><Check size={15} /></button> : <button className="secondary" disabled={!customModel || !status?.ollama.available || busyAction === `download:${customModel}`} onClick={() => void download(customModel)}><Download size={15} /></button>}</div></div>

      <section className="permission-section"><div className="panel-heading"><div><p className="eyebrow">{t("toolPermission")}</p><h2>{t("dangerousTools")}</h2></div><ShieldCheck size={20} /></div><p className="secure-note">{t("dangerousToolsDescription")}</p><label className="checkbox-label dangerous-tools-toggle"><input type="checkbox" checked={dangerousToolsEnabled} disabled={busyAction === "dangerous-tools"} onChange={(event) => void toggleDangerousTools(event.target.checked)} /> {t("enableDangerousTools")}</label></section>

      <section className="provider-section"><div className="panel-heading"><div><p className="eyebrow">{t("providers")}</p><h2>{t("providerManagement")}</h2></div><Plus size={20} /></div><p className="secure-note"><ShieldCheck size={15} />{t("secureKeyNotice")}</p><div className="preset-row"><span>{t("presets")}</span>{presets.map((preset) => <button key={preset.preset} className="secondary" onClick={() => { setDraft({ ...preset, api_key: "", fallback_enabled: false }); setDiscoveredModels([]); }}>{preset.name}</button>)}</div>
        <div className="provider-form">
          <label>{t("providerName")}<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <label>{t("baseUrl")}<input type="url" value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} /></label>
          <label>{t("apiKey")}<input type="password" value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} autoComplete="off" /><small>{t("keyOptional")}</small></label>
          <label>{t("modelName")}<input list="remote-models" value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} /><datalist id="remote-models">{discoveredModels.map((model) => <option key={model} value={model} />)}</datalist></label>
          <button className="secondary discover-button" disabled={!draft.base_url || !draft.api_key || busyAction === "discover"} onClick={() => void discoverModels()}><ListRestart size={15} /> {t("discoverModels")}</button>
          <label className="checkbox-label"><input type="checkbox" checked={draft.fallback_enabled} onChange={(event) => setDraft({ ...draft, fallback_enabled: event.target.checked })} /> {t("fallback")}</label>
          <button className="primary" disabled={!draft.name || !draft.base_url || !draft.model || !draft.api_key || busyAction === "save"} onClick={() => void save()}><Save size={15} /> {t("save")}</button>
        </div>
        <div className="provider-list">{providers.length === 0 ? <p className="muted">{t("noProviders")}</p> : providers.map((provider) => <article key={provider.id} className="provider-card"><div><strong>{provider.name}</strong><small>{provider.model} · {provider.api_key_masked ?? t("unavailable")}</small></div><div><button className={`secondary select-provider ${selectedProvider === provider.id ? "active" : ""}`} onClick={() => onSelectProvider(selectedProvider === provider.id ? undefined : provider)}>{selectedProvider === provider.id ? t("selected") : t("select")}</button><button className="icon-button" title={t("testConnection")} disabled={busyAction === `test:${provider.id}`} onClick={() => void test(provider)}><Wifi size={15} /></button><button className="icon-button danger" title={t("delete")} onClick={() => void deleteProvider(provider.id).then(refreshProviders)}><Trash2 size={15} /></button></div></article>)}</div>
      </section>
      {notice && <p className="settings-notice"><KeyRound size={14} />{notice}</p>}
    </aside>
  );
}
