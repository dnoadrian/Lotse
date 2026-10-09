// Ersteinrichtung: erster Benutzer im Browser (nur solange es keinen gibt, mit Einmal-Token).
import { useState, type FormEvent } from "react";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import { Icon } from "../components/Icons";

export function SetupForm({ onDone }: { onDone: (username: string) => void }) {
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== repeat) {
      setError("Die Passwörter stimmen nicht überein.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ep.completeSetup(token.trim(), username.trim(), password);
      onDone(username.trim().toLowerCase());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack-18" onSubmit={submit} noValidate>
      <div className="stack-4">
        <h1 className="login-title">Ersteinrichtung</h1>
        <span className="muted">Lege den ersten Benutzer an. Das geht nur einmal.</span>
      </div>
      {error ? (
        <div className="error-box" role="alert">
          <Icon name="info" size={16} strokeWidth={2} className="error-box-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      <label className="field">
        Einrichtungs-Token
        <input className="input mono" type="password" autoComplete="off" required maxLength={256} value={token}
          onChange={(e) => setToken(e.target.value)} />
        <span className="muted small field-hint">Steht im Render-Dashboard unter Environment → LOTSE_SETUP_TOKEN.</span>
      </label>
      <label className="field">
        Benutzername
        <input className="input" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false}
          required minLength={3} maxLength={64} value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label className="field">
        Passwort
        <input className="input" type="password" autoComplete="new-password" required maxLength={256} value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <span className="muted small field-hint">Mindestens 4 Zeichen.</span>
      </label>
      <label className="field">
        Passwort wiederholen
        <input className="input" type="password" autoComplete="new-password" required maxLength={256} value={repeat}
          onChange={(e) => setRepeat(e.target.value)} />
      </label>
      <button type="submit" className="btn btn-primary btn-block"
        disabled={busy || !token.trim() || username.trim().length < 3 || password.length < 4 || !repeat}>
        {busy ? "Wird angelegt …" : "Benutzer anlegen"}
      </button>
    </form>
  );
}
