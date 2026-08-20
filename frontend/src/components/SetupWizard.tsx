import { useState } from "react";
import { Check, ChevronLeft, ChevronRight, Cloud, LockKeyhole, MonitorCog, Sparkles } from "lucide-react";
import type { Locale, SetupCheck } from "../types/runtime";
import { translate, type TranslationKey } from "../i18n";

interface Props {
  locale: Locale;
  checks: SetupCheck[];
  onComplete: () => void;
}

const stepIcons = [Sparkles, MonitorCog, Sparkles, Cloud, LockKeyhole, Check];
const stepKeys: TranslationKey[] = ["stepWelcome", "stepRuntime", "stepModels", "stepCloud", "stepPermissions", "stepFinish"];
const copyKeys: Array<TranslationKey | null> = ["onboardingWelcome", null, "onboardingModels", "onboardingCloud", "onboardingPermissions", "onboardingFinish"];

export function SetupWizard({ locale, checks, onComplete }: Props) {
  const [step, setStep] = useState(0);
  const Icon = stepIcons[step];
  const label = translate(locale, stepKeys[step]);
  const copyKey = copyKeys[step];

  return (
    <div className="wizard-backdrop" role="dialog" aria-modal="true" aria-label={translate(locale, "setup")}>
      <section className="wizard-card">
        <div className="wizard-progress" aria-label={`${translate(locale, "setupStep")} ${step + 1} ${translate(locale, "of")} 6`}>
          {stepKeys.map((key, index) => <span key={key} className={index <= step ? "done" : ""} />)}
        </div>
        <div className="wizard-icon"><Icon size={28} /></div>
        <p className="eyebrow">{translate(locale, "setup")} · {translate(locale, "setupStep")} {step + 1}/6</p>
        <h2>{label}</h2>
        {step === 1 ? <CheckList checks={checks.filter((item) => ["os", "runtime", "ollama"].includes(item.key))} /> : <p>{copyKey ? translate(locale, copyKey) : ""}</p>}
        <footer className="wizard-actions">
          {step > 0 && <button className="secondary" onClick={() => setStep((value) => value - 1)}><ChevronRight size={16} /> {translate(locale, "previous")}</button>}
          {step < 5 ? <button className="primary" onClick={() => setStep((value) => value + 1)}>{translate(locale, "next")} <ChevronLeft size={16} /></button> : <button className="primary" onClick={onComplete}>{translate(locale, "complete")}</button>}
        </footer>
      </section>
    </div>
  );
}

function CheckList({ checks }: { checks: SetupCheck[] }) {
  return <ul className="check-list">{checks.map((check) => <li key={check.key}><span className={`status-dot ${check.status}`} /> <strong>{check.label}</strong><small>{check.detail}</small></li>)}</ul>;
}
