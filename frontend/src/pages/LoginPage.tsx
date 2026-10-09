import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, errorText } from "../api/client";
import * as ep from "../api/endpoints";
import { LogoMark } from "../components/Logo";
import { ThemeToggle } from "../components/Layout";
import { Icon } from "../components/Icons";
import { useAuth } from "../lib/auth";
import { formatCountdown } from "../lib/format";
import { SetupForm } from "./SetupForm";

interface LocationState {
  from?: string;
}

function useCountdown(seconds: number | null): number | null {
  const [left, setLeft] = useState<number | null>(seconds);
  useEffect(() => {
    setLeft(seconds);
    if (!seconds) return;
    const until = Date.now() + seconds * 1000;
    const t = window.setInterval(() => {
      const rest = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setLeft(rest);
      if (rest === 0) window.clearInterval(t);
    }, 1000);
    return () => window.clearInterval(t);
  }, [seconds]);
  return left;
}

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from;
  const target = from && from.startsWith("/") && !from.startsWith("//") && from !== "/login" ? from : "/";

  const [step, setStep] = useState<1 | 2>(auth.mfaPending ? 2 : 1);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const left = useCountdown(retryAfter);
  const codeRef = useRef<HTMLInputElement>(null);
  const userRef = useRef<HTMLInputElement>(null);

  const [setupNeeded, setSetupNeeded] = useState(false);
  const [setupDone, setSetupDone] = useState(false);
  useEffect(() => {
    ep.getSetupStatus()
      .then((r) => setSetupNeeded(r.needed))
      .catch(() => setSetupNeeded(false));
  }, []);

  useEffect(() => {
    if (auth.mfaPending) setStep(2);
  }, [auth.mfaPending]);

  useEffect(() => {
    if (step === 2) codeRef.current?.focus();
    else userRef.current?.focus();
  }, [step]);

  if (auth.status === "authenticated") return <Navigate to={target} replace />;

  function handleError(err: unknown) {
    if (err instanceof ApiError && err.status === 429) {
      setRetryAfter(err.retryAfter);
      setError(err.detail);
    } else {
      setRetryAfter(null);
      setError(errorText(err));
    }
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await ep.login(username.trim(), password);
      setPassword("");
      if (res.mfa_required) {
        setStep(2);
      } else if (res.csrf_token) {
        await auth.completeLogin(res.csrf_token);
        navigate(target, { replace: true });
      }
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const clean = code.replace(/\s+/g, "");
    if (!/^\d{6}$/.test(clean)) {
      setError("Bitte den 6-stelligen Code eingeben.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await ep.submitTotp(clean);
      await auth.completeLogin(res.csrf_token);
      navigate(target, { replace: true });
    } catch (err) {
      setCode("");
      if (err instanceof ApiError && err.status === 429) {
        // Server verwirft die halbe Sitzung – neu mit Passwort anmelden
        handleError(err);
        setStep(1);
      } else if (err instanceof ApiError && err.status === 401 && /zuerst/i.test(err.detail)) {
        setError(err.detail);
        setStep(1);
      } else {
        handleError(err);
      }
    } finally {
      setBusy(false);
    }
  }

  function back() {
    setError(null);
    setCode("");
    setStep(1);
    void ep
      .logout()
      .catch(() => undefined)
      .finally(() => void auth.refresh());
  }

  const limited = retryAfter !== null && left !== null && left > 0;

  return (
    <div className="login-page">
      <div className="login-top">
        <ThemeToggle compact />
      </div>
      <div className="login-col">
        <div className="login-brand">
          <LogoMark size={56} />
          <span className="login-wordmark">Lotse</span>
        </div>

        <div className="card login-card">
          {auth.status === "unreachable" ? (
            <div className="error-box" role="alert">
              <Icon name="info" size={16} strokeWidth={2} className="error-box-icon" />
              <span>
                Der Server ist nicht erreichbar.{" "}
                <button type="button" className="link-btn" onClick={() => void auth.refresh()}>
                  Erneut versuchen
                </button>
              </span>
            </div>
          ) : null}

          {setupNeeded ? (
            <SetupForm
              onDone={(name) => {
                setSetupNeeded(false);
                setSetupDone(true);
                setUsername(name);
              }}
            />
          ) : null}
          {setupDone ? (
            <div className="banner banner-success" role="status">
              Benutzer angelegt. Melde dich jetzt an.
            </div>
          ) : null}
          {setupNeeded ? null : step === 1 ? (
            <form className="stack-18" onSubmit={submitPassword} noValidate>
              <div className="stack-4">
                <h1 className="login-title">Anmelden</h1>
                <span className="muted">Schritt 1 von 2</span>
              </div>
              {error ? (
                <div className="error-box" role="alert">
                  <Icon name="info" size={16} strokeWidth={2} className="error-box-icon" />
                  <span>
                    {error}
                    {limited ? (
                      <>
                        {" "}
                        Bitte warte <strong className="mono">{formatCountdown(left ?? 0)}</strong> Minuten.
                      </>
                    ) : null}
                  </span>
                </div>
              ) : null}
              <label className="field">
                Benutzername
                <input
                  ref={userRef}
                  className="input"
                  type="text"
                  name="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  placeholder="admin"
                  required
                  maxLength={64}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </label>
              <label className="field">
                Passwort
                <input
                  className="input"
                  type="password"
                  name="password"
                  autoComplete="current-password"
                  required
                  maxLength={256}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <button type="submit" className="btn btn-primary btn-block" disabled={busy || !username.trim() || !password || limited}>
                {busy ? "Wird geprüft …" : "Weiter"}
              </button>
            </form>
          ) : (
            <form className="stack-18" onSubmit={submitCode} noValidate>
              <div className="stack-4">
                <h1 className="login-title">Bestätigungscode</h1>
                <span className="muted">Schritt 2 von 2 · Code aus deiner Authenticator-App</span>
              </div>
              {error ? (
                <div className="error-box" role="alert">
                  <Icon name="info" size={16} strokeWidth={2} className="error-box-icon" />
                  <span>{error}</span>
                </div>
              ) : null}
              <label className="field">
                6-stelliger Code
                <input
                  ref={codeRef}
                  className="input input-code"
                  type="text"
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="000000"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                />
              </label>
              <button type="submit" className="btn btn-primary btn-block" disabled={busy || code.length !== 6}>
                {busy ? "Wird geprüft …" : "Anmelden"}
              </button>
              <button type="button" className="btn btn-link" onClick={back}>
                Zurück
              </button>
            </form>
          )}
        </div>

        <p className="login-foot muted">Nur über HTTPS erreichbar. Sitzungen laufen nach Inaktivität automatisch ab.</p>
      </div>
    </div>
  );
}
