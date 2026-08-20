import { useCallback, useEffect, useState } from "react";
import { Download, Plus, Save, ShieldCheck, Trash2, Wifi } from "lucide-react";
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
  pullModel: (model: string) => Promise<void>;
  selectedProvider?: string;
  onSelectProvider: (provider?: CustomProvider) => void;
}

const recommended = ["qwen2.5-coder:7b", "qwen2.5-coder:14b"];
const blankDraft: ProviderDraft = { name: "", base_url: "", api_key: "", model: "", fallback_enabled: false };
const presets = [
  { name: "NVIDIA NIM", base_url: "https://integrate.api.nvidia.com/v1", model: "meta/llama-3.1-70b-instruct", preset: "nvidia" },
  { name: "Mistral", base_url: "https://api.mistral.ai/v1", model: "mistral-small-latest", preset: "mistral" },
  { name: "Groq", base_url: "https://api.groq.com/openai/v1", model: "llama-3.1-8b-instant", preset: "groq" },
];

export function SettingsPanel({ locale, status, listProviders, saveProvider, deleteProvider, testProvider, pullModel, selectedProvider, onSelectProvider }: Props) {
  const [providers, setProviders] = useState<CustomProvider[]>([]);
  const [draft, setDraft] = useState<ProviderDraft>(blankDraft);
  const [customModel, setCustomModel] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  const refreshProviders = useCallback(async () => {
    try { setProviders(await listProviders()); } catch { setProviders([]); }
  }, [listProviders]);

  useEffect(() => { void refreshProviders(); }, [refreshProviders]);

  const download = async (model: string) => {
    if (!window.confirm(t("downloadConfirm"))) return;
    try { await pullModel(model); setNotice(t("downloadStarted")); } catch { setNotice(t("unavailable")); }
  };

  const save = async () => {
    try { await saveProvider(draft); setDraft(blankDraft); setNotice(t("providerSaved")); await refreshProviders(); } catch { setNotice(t("unavailable")); }
  };

  return (
    <aside className="settings-panel" aria-label={t("settings")}>
      <div className="panel-heading"><div><p className="eyebrow">{t("settings")}</p><h2>{t("modelManagement")}</h2></div><ShieldCheck size={21} /></div>
      <div className="model-grid">
        {recommended.map((model) => {
          const installed = status?.ollama.models.includes(model) ?? false;
          return <article className="model-card" key={model}><strong>{model}</strong><span className={installed ? "good" : "muted"}>{installed ? t("installed") : t("notInstalled")}</span><button className="secondary" disabled={installed || !status?.ollama.available} onClick={() => void download(model)}><Download size={15} /> {t("downloadModel")}</button></article>;
        })}
      </div>
      <div className="custom-model"><label>{t("customModel")}</label><div><input value={customModel} onChange={(event) => setCustomModel(event.target.value)} /><button className="secondary" disabled={!customModel || !status?.ollama.available} onClick={() => void download(customModel)}><Download size={15} /></button></div></div>

      <section className="provider-section"><div className="panel-heading"><div><p className="eyebrow">{t("providers")}</p><h2>{t("providerManagement")}</h2></div><Plus size={20} /></div><p className="secure-note"><ShieldCheck size={15} />{t("secureKeyNotice")}</p><div className="preset-row"><span>{t("presets")}</span>{presets.map((preset) => <button key={preset.preset} className="secondary" onClick={() => setDraft({ ...preset, api_key: "", fallback_enabled: false })}>{preset.name}</button>)}</div>
        <div className="provider-form">
          <label>{t("providerName")}<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <label>{t("baseUrl")}<input type="url" value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} /></label>
          <label>{t("modelName")}<input value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} /></label>
          <label>{t("apiKey")}<input type="password" value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} /><small>{t("keyOptional")}</small></label>
          <label className="checkbox-label"><input type="checkbox" checked={draft.fallback_enabled} onChange={(event) => setDraft({ ...draft, fallback_enabled: event.target.checked })} /> {t("fallback")}</label>
          <button className="primary" disabled={!draft.name || !draft.base_url || !draft.model || !draft.api_key} onClick={() => void save()}><Save size={15} /> {t("save")}</button>
        </div>
        <div className="provider-list">{providers.length === 0 ? <p className="muted">{t("noProviders")}</p> : providers.map((provider) => <article key={provider.id} className="provider-card"><div><strong>{provider.name}</strong><small>{provider.model} · {provider.api_key_masked ?? t("notInstalled")}</small></div><div><button className={`secondary select-provider ${selectedProvider === provider.id ? "active" : ""}`} onClick={() => onSelectProvider(selectedProvider === provider.id ? undefined : provider)}>{selectedProvider === provider.id ? t("selected") : t("select")}</button><button className="icon-button" title={t("testConnection")} onClick={() => void testProvider(provider.id).then(() => setNotice(t("ready"))).catch(() => setNotice(t("unavailable")))}><Wifi size={15} /></button><button className="icon-button danger" title={t("delete")} onClick={() => void deleteProvider(provider.id).then(refreshProviders)}><Trash2 size={15} /></button></div></article>)}</div>
      </section>
      {notice && <p className="settings-notice">{notice}</p>}
    </aside>
  );
}
