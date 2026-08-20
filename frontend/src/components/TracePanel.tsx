import { Activity, AlertTriangle, CheckCircle2, Clock3, ShieldCheck, Wrench } from "lucide-react";
import type { TraceEvent } from "../types/runtime";
import type { Locale } from "../types/runtime";
import { translate } from "../i18n";

interface Props {
  locale: Locale;
  traces: TraceEvent[];
  connected: boolean;
}

const iconFor = (category: TraceEvent["category"]) => {
  if (category === "error") return <AlertTriangle size={15} />;
  if (category === "tool") return <Wrench size={15} />;
  if (category === "permission") return <ShieldCheck size={15} />;
  if (category === "result") return <CheckCircle2 size={15} />;
  return <Activity size={15} />;
};

export function TracePanel({ locale, traces, connected }: Props) {
  return (
    <section className="trace-panel" aria-live="polite">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{translate(locale, "trace")}</p>
          <h2>{connected ? translate(locale, "runtimeConnected") : translate(locale, "runtimeWaiting")}</h2>
        </div>
        <span className={`connection ${connected ? "online" : "offline"}`}>
          <span /> {connected ? translate(locale, "live") : translate(locale, "offline")}
        </span>
      </div>
      {traces.length === 0 ? (
        <div className="trace-empty"><Clock3 size={18} /> {translate(locale, "noTrace")}</div>
      ) : (
        <ol className="trace-list">
          {traces.map((trace) => (
            <li key={trace.id} className={`trace-item ${trace.category}`}>
              <span className="trace-icon">{iconFor(trace.category)}</span>
              <span className="trace-time">{new Date(trace.timestamp).toLocaleTimeString(locale)}</span>
              <span className="trace-message">{trace.message}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
