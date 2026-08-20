import { useEffect, useMemo, useState } from "react";
import { Bot, Globe2, Moon, Plus, Send, Settings, ShieldCheck, Sun, XOctagon } from "lucide-react";
import { SettingsPanel } from "./components/SettingsPanel";
import { SetupWizard } from "./components/SetupWizard";
import { TracePanel } from "./components/TracePanel";
import { translate } from "./i18n";
import { useRuntime } from "./hooks/useRuntime";
import type { AgentResponse, CustomProvider, Locale, PrivacyMode } from "./types/runtime";

const SESSION_ID = crypto.randomUUID();

export default function App() {
  const [locale, setLocale] = useState<Locale>((localStorage.getItem("locale") as Locale) || "ar");
  const [theme, setTheme] = useState<"dark" | "light">((localStorage.getItem("theme") as "dark" | "light") || "dark");
  const [privacyMode, setPrivacyMode] = useState<PrivacyMode>((localStorage.getItem("privacyMode") as PrivacyMode) || "local");
  const [message, setMessage] = useState("");
  const [conversation, setConversation] = useState<Array<{ role: "user" | "agent"; text: string }>>([]);
  const [showSetup, setShowSetup] = useState(() => localStorage.getItem("setupComplete") !== "true");
  const [busy, setBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedCloud, setSelectedCloud] = useState<CustomProvider | undefined>();
  const [pendingApproval, setPendingApproval] = useState<AgentResponse | null>(null);
  const { status, setup, traces, connected, error, dangerousToolsEnabled, submit, stop, decidePermission, setDangerousTools, listProviders, saveProvider, deleteProvider, testProvider, discoverProviderModels, setActiveModel, pullModel, clearTraces } = useRuntime(SESSION_ID);
  const t = useMemo(() => (key: Parameters<typeof translate>[1]) => translate(locale, key), [locale]);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("locale", locale);
    localStorage.setItem("theme", theme);
    localStorage.setItem("privacyMode", privacyMode);
  }, [locale, theme, privacyMode]);

  async function send() {
    const text = message.trim();
    if (!text || busy) return;
    const usingCloud = privacyMode === "hybrid" && Boolean(selectedCloud);
    if (usingCloud && !window.confirm(`${t("cloudDisclosure")}\n${t("providerName")}: ${selectedCloud?.name}\n${t("modelName")}: ${selectedCloud?.model}`)) return;
    setConversation((items) => [...items, { role: "user", text }]);
    setMessage("");
    setBusy(true);
    try {
      const response: AgentResponse = await submit(text, {
        demoMode: !status?.ollama.available && privacyMode === "local",
        selectedProvider: usingCloud ? selectedCloud?.id : "ollama",
        privacyMode: privacyMode === "hybrid" ? "hybrid" : "local_only",
        cloudConsent: usingCloud,
      });
      setConversation((items) => [...items, { role: "agent", text: response.message }]);
      if (response.state === "awaiting_permission" && response.tool_calls.length > 0) setPendingApproval(response);
    } catch {
      setConversation((items) => [...items, { role: "agent", text: error || t("runtimeUnavailable") }]);
    } finally {
      setBusy(false);
    }
  }

  async function emergencyStop() {
    await stop();
    setPendingApproval(null);
    setBusy(false);
  }

  async function resolvePermission(decision: "allow_once" | "allow_always" | "deny") {
    if (!pendingApproval || busy) return;
    setBusy(true);
    try {
      const response = await decidePermission(pendingApproval.run_id, decision);
      setConversation((items) => [...items, { role: "agent", text: response.message }]);
    } catch {
      setConversation((items) => [...items, { role: "agent", text: decision === "deny" ? t("permissionDenied") : t("permissionFailed") }]);
    } finally {
      setPendingApproval(null);
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><Bot size={20} /></span><div><strong>{t("appName")}</strong><small>{privacyMode === "local" ? t("secureLocal") : t("hybrid")}</small></div></div>
        <div className="header-actions">
          <button className="icon-button" title={t("settings")} onClick={() => setShowSettings((value) => !value)}><Settings size={18} /></button>
          <button className="icon-button" title={t("language")} onClick={() => setLocale(locale === "ar" ? "en" : "ar")}><Globe2 size={18} /></button>
          <button className="icon-button" title={theme === "dark" ? t("light") : t("dark")} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}</button>
        </div>
      </header>

      <section className="privacy-bar">
        <ShieldCheck size={17} /><strong>{privacyMode === "local" ? t("localOnly") : t("hybrid")}</strong><span>{privacyMode === "local" ? t("localProcessing") : t("cloudNotice")}</span>
        <button onClick={() => setPrivacyMode(privacyMode === "local" ? "hybrid" : "local")}>{privacyMode === "local" ? t("hybrid") : t("localOnly")}</button>
      </section>

      <section className="model-strip">
        <span className={`status-dot ${status?.ollama.available ? "ready" : "warning"}`} /><div><small>{t("model")}</small><strong>{status ? (status.ollama.models[0] ?? t("noActiveModel")) : t("modelWaiting")}</strong></div>
        <div className="model-status"><small>{t("status")}</small><strong>{!status ? t("runtimeWaiting") : status.ollama.available ? t("ready") : t("unavailable")}</strong></div>
      </section>

      <section className="chat" aria-label={t("appName")}>
        {conversation.length === 0 ? <div className="empty-chat"><div className="empty-icon"><Bot size={27} /></div><h1>{t("appName")}</h1><p>{t("secureLocal")}. {t("chatIntro")}</p></div> : conversation.map((item, index) => <article key={`${item.role}-${index}`} className={`message ${item.role}`}><span>{item.role === "user" ? t("you") : t("agent")}</span><p>{item.text}</p></article>)}
        {pendingApproval && pendingApproval.tool_calls[0] && <section className="permission-card"><div><ShieldCheck size={18} /><strong>{t("permissionRequired")}</strong></div><p>{t("permissionActionDetails")}</p><code>{pendingApproval.tool_calls[0].name}</code><small>{pendingApproval.tool_calls[0].rationale}</small><pre>{JSON.stringify(pendingApproval.tool_calls[0].arguments, null, 2)}</pre><div className="permission-actions"><button className="secondary" disabled={busy} onClick={() => void resolvePermission("deny")}>{t("deny")}</button><button className="secondary" disabled={busy} onClick={() => void resolvePermission("allow_once")}>{t("allowOnce")}</button>{pendingApproval.tool_calls[0].permission !== "dangerous" && <button className="primary" disabled={busy} onClick={() => void resolvePermission("allow_always")}>{t("allowAlways")}</button>}</div></section>}
      </section>

      <div className="composer">
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder={t("placeholder")} rows={2} />
        <button className="send-button" disabled={!message.trim() || busy} onClick={() => void send()}><Send size={18} /> <span>{t("send")}</span></button>
      </div>

      <div className="workspace-actions"><button className="secondary" onClick={() => { setConversation([]); clearTraces(); }}><Plus size={16} /> {t("newChat")}</button><button className="stop" disabled={!busy} onClick={() => void emergencyStop()}><XOctagon size={16} /> {t("stopAgent")}</button></div>
      <TracePanel locale={locale} traces={traces} connected={connected} />
      {showSettings && <SettingsPanel locale={locale} status={status} listProviders={listProviders} saveProvider={saveProvider} deleteProvider={deleteProvider} testProvider={testProvider} discoverProviderModels={discoverProviderModels} setActiveModel={setActiveModel} pullModel={pullModel} dangerousToolsEnabled={dangerousToolsEnabled} setDangerousTools={setDangerousTools} selectedProvider={selectedCloud?.id} onSelectProvider={setSelectedCloud} />}
      {showSetup && <SetupWizard locale={locale} checks={setup?.checks ?? []} onComplete={() => { localStorage.setItem("setupComplete", "true"); setShowSetup(false); }} />}
    </main>
  );
}
