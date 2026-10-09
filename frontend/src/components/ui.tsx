// Kleine, wiederverwendbare Bausteine.
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./Icons";

export type BannerKind = "success" | "error" | "info" | "warning";

export function Banner({
  kind,
  title,
  children,
  onClose,
  role,
}: {
  kind: BannerKind;
  title?: ReactNode;
  children?: ReactNode;
  onClose?: () => void;
  role?: "status" | "alert";
}) {
  const icon = kind === "success" ? "check" : kind === "info" ? "info" : "alert";
  return (
    <div className={`banner banner-${kind}`} role={role ?? (kind === "error" ? "alert" : "status")}>
      <Icon name={icon} size={18} strokeWidth={2.2} className="banner-icon" />
      <div className="banner-body">
        {title ? <span className="banner-title">{title}</span> : null}
        {children ? <div className="banner-text">{children}</div> : null}
      </div>
      {onClose ? (
        <button type="button" className="btn btn-ghost btn-sm banner-close" onClick={onClose}>
          Schließen
        </button>
      ) : null}
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      <Icon name="info" size={16} strokeWidth={2} className="error-box-icon" />
      <span>{children}</span>
    </div>
  );
}

export function Spinner({ label = "Wird geladen …" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {intro ? <p className="muted page-intro">{intro}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </header>
  );
}

export function ProgressBar({ value, label, className }: { value: number; label: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      className={`progress${className ? " " + className : ""}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Reagiert auf Media Queries (z. B. Telefonbreite). */
export function useMediaQuery(query: string): boolean {
  const get = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false);
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mql = window.matchMedia(query);
    const handler = () => setMatches(mql.matches);
    handler();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

export const PHONE_QUERY = "(max-width: 760px)";

export function useIsPhone(): boolean {
  return useMediaQuery(PHONE_QUERY);
}

/** Text in die Zwischenablage kopieren (mit Fallback). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* Fallback unten */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.className = "offscreen";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function CopyButton({ text, label = "Kopieren", ariaLabel }: { text: string; label?: string; ariaLabel?: string }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(t);
  }, [state]);
  return (
    <button
      type="button"
      className="btn btn-secondary btn-sm"
      aria-label={ariaLabel}
      onClick={async () => setState((await copyText(text)) ? "ok" : "fail")}
    >
      <Icon name={state === "ok" ? "check" : "copy"} size={16} />
      <span aria-live="polite">{state === "ok" ? "Kopiert" : state === "fail" ? "Nicht möglich" : label}</span>
    </button>
  );
}
