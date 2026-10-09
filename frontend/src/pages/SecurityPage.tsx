// „Sicherheit“: Zwei-Faktor-Anmeldung, Passwort, aktive Sitzungen.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { SecurityOverview, TotpSetup } from "../api/types";
import { Banner, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { useAuth } from "../lib/auth";
import { formatDateTime } from "../lib/format";

const MIN_PASSWORD = 4;

function groupSecret(secret: string): string {
  return secret.replace(/(.{4})/g, "$1 ").trim();
}

function digitsOnly(v: string): string {
  return v.replace(/\D/g, "").slice(0, 8);
}

function TotpCard({ enabled, onChanged }: { enabled: boolean; onChanged: (enabled: boolean) => void }) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function begin() {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      setSetup(await ep.totpSetup());
      setCode("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function enable(e: FormEvent) {
    e.preventDefault();
    if (code.length < 6) return;
    setBusy(true);
    setError(null);
    try {
      await ep.totpEnable(code);
      setSetup(null);
      setCode("");
      setDone("Zwei-Faktor-Anmeldung ist jetzt aktiv.");
      onChanged(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function disable(e: FormEvent) {
    e.preventDefault();
    if (!password || code.length < 6) return;
    setBusy(true);
    setError(null);
    try {
      await ep.totpDisable(password, code);
      setPassword("");
      setCode("");
      setDone("Zwei-Faktor-Anmeldung wurde deaktiviert.");
      onChanged(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="totp-h" className="card stack-18">
      <div className="conn-head">
        <div className="stack-2">
          <h2 id="totp-h">Zwei-Faktor-Anmeldung</h2>
          <span className="muted small">Code aus einer Authenticator-App (TOTP)</span>
        </div>
        {enabled ? (
          <span className="pill pill-green">
            <span className="dot dot-green" aria-hidden="true" />
            Aktiv
          </span>
        ) : (
          <span className="pill pill-muted">
            <span className="dot dot-muted" aria-hidden="true" />
            Nicht aktiv
          </span>
        )}
      </div>

      {done ? (
        <p className="text-green no-margin" role="status">
          {done}
        </p>
      ) : null}
      {error ? <ErrorBox>{error}</ErrorBox> : null}

      {enabled ? (
        <form className="stack-18" onSubmit={disable} noValidate>
          <p className="muted no-margin">Zum Deaktivieren brauchst du dein Passwort und einen aktuellen Code.</p>
          <label className="field">
            Passwort
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label className="field">
            Aktueller Code
            <input
              className="input mono"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={8}
              value={code}
              onChange={(e) => setCode(digitsOnly(e.target.value))}
            />
          </label>
          <div className="row-wrap">
            <button type="submit" className="btn btn-danger-outline" disabled={busy || !password || code.length < 6}>
              {busy ? "Wird geprüft …" : "2FA deaktivieren"}
            </button>
          </div>
        </form>
      ) : setup ? (
        <form className="stack-18" onSubmit={enable} noValidate>
          <ol className="steps-list">
            <li>Scanne den QR-Code mit deiner Authenticator-App.</li>
            <li>Oder gib den Schlüssel von Hand ein.</li>
            <li>Bestätige mit dem angezeigten 6-stelligen Code.</li>
          </ol>
          <div className="totp-setup">
            <img
              className="qr"
              src={"data:image/svg+xml;base64," + setup.qr_svg_base64}
              alt="QR-Code für die Authenticator-App"
              width={200}
              height={200}
            />
            <div className="stack-6 min-0">
              <span className="muted small">Schlüssel</span>
              <code className="secret">{groupSecret(setup.secret)}</code>
            </div>
          </div>
          <label className="field">
            6-stelliger Code
            <input
              className="input input-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              value={code}
              onChange={(e) => setCode(digitsOnly(e.target.value).slice(0, 6))}
            />
          </label>
          <div className="row-wrap">
            <button type="submit" className="btn btn-primary" disabled={busy || code.length !== 6}>
              {busy ? "Wird geprüft …" : "Aktivieren"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setSetup(null)} disabled={busy}>
              Abbrechen
            </button>
          </div>
        </form>
      ) : (
        <div className="stack-18">
          <p className="muted no-margin">
            Schütze dein Konto zusätzlich: Nach dem Passwort fragt Lotse dann einen Code aus deiner Authenticator-App ab.
          </p>
          <div className="row-wrap">
            <button type="button" className="btn btn-primary" onClick={() => void begin()} disabled={busy}>
              {busy ? "Wird vorbereitet …" : "2FA einrichten"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    if (next.length < MIN_PASSWORD) {
      setError(`Das neue Passwort muss mindestens ${MIN_PASSWORD} Zeichen lang sein.`);
      return;
    }
    if (next !== repeat) {
      setError("Die beiden neuen Passwörter stimmen nicht überein.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await ep.changePassword(current, next);
      setCurrent("");
      setNext("");
      setRepeat("");
      setDone(
        res.other_sessions_revoked > 0
          ? `Passwort geändert. ${res.other_sessions_revoked} andere ${res.other_sessions_revoked === 1 ? "Sitzung wurde" : "Sitzungen wurden"} beendet.`
          : "Passwort geändert.",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="pw-h" className="card">
      <form className="stack-18" onSubmit={submit} noValidate>
        <div className="stack-2">
          <h2 id="pw-h">Passwort ändern</h2>
          <span className="muted small">Andere Sitzungen werden danach beendet.</span>
        </div>
        <label className="field">
          Aktuelles Passwort
          <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="field">
          Neues Passwort
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD}
            maxLength={256}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            aria-describedby="pw-hint"
          />
          <span id="pw-hint" className={`small field-hint ${next && next.length < MIN_PASSWORD ? "text-red" : "muted"}`}>
            Mindestens {MIN_PASSWORD} Zeichen. Eine längere Passphrase ist besser als Sonderzeichen.
          </span>
        </label>
        <label className="field">
          Neues Passwort wiederholen
          <input className="input" type="password" autoComplete="new-password" maxLength={256} value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </label>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
        {done ? (
          <p className="text-green no-margin" role="status">
            {done}
          </p>
        ) : null}
        <div className="row-wrap">
          <button type="submit" className="btn btn-primary" disabled={busy || !current || !next || !repeat}>
            {busy ? "Wird gespeichert …" : "Passwort ändern"}
          </button>
        </div>
      </form>
    </section>
  );
}

export function SecurityPage() {
  const auth = useAuth();
  const [overview, setOverview] = useState<SecurityOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setOverview(await ep.getSecurityOverview());
      setError(null);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function revoke(id: number) {
    setRevoking(id);
    try {
      await ep.revokeSession(id);
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="page">
      <PageHeader title="Sicherheit" intro="Zwei-Faktor-Anmeldung, Passwort und angemeldete Geräte." />
      {error ? (
        <Banner kind="error" onClose={() => setError(null)}>
          {error}
        </Banner>
      ) : null}
      {!overview ? (
        error ? null : <Spinner />
      ) : (
        <>
          <div className="conn-grid">
            <TotpCard
              enabled={overview.totp_enabled}
              onChanged={(enabled) => {
                setOverview((o) => (o ? { ...o, totp_enabled: enabled } : o));
                auth.setTotpEnabled(enabled);
              }}
            />
            <PasswordCard />
          </div>

          <section aria-labelledby="sess-h" className="card stack-14">
            <div className="stack-2">
              <h2 id="sess-h">Aktive Sitzungen</h2>
              <span className="muted small">Beende Sitzungen, die du nicht kennst.</span>
            </div>
            <ul className="session-list">
              {overview.sessions.map((s) => (
                <li key={s.id} className="session-item">
                  <div className="stack-2 min-0">
                    <span className="strong break">{s.user_agent || "Unbekanntes Gerät"}</span>
                    <span className="muted small">
                      <span className="mono">{s.ip || "—"}</span> · angemeldet {formatDateTime(s.created_at)} · zuletzt aktiv{" "}
                      {formatDateTime(s.last_seen)}
                    </span>
                  </div>
                  {s.current ? (
                    <span className="pill pill-blue">Diese Sitzung</span>
                  ) : (
                    <button type="button" className="btn btn-secondary btn-sm text-red" onClick={() => void revoke(s.id)} disabled={revoking === s.id}>
                      {revoking === s.id ? "Wird beendet …" : "Beenden"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
