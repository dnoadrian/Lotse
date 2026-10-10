// „Verbindungen“: Postfächer verwalten und Scans starten (Connect.dc.html).
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Account, AppConfig } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { PasswordInput } from "../components/PasswordInput";
import { ScanProgressList } from "../components/ScanProgress";
import { Banner, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { isActive, useScans } from "../lib/scans";

const SINCE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Alle Nachrichten" },
  { value: "1825", label: "Letzte 5 Jahre" },
  { value: "365", label: "Letztes Jahr" },
];

interface ImapFormValues {
  label: string;
  host: string;
  port: string;
  username: string;
  password: string;
}

function ImapFields({
  values,
  onChange,
  passwordHint,
  idPrefix,
  allowedPorts,
}: {
  values: ImapFormValues;
  onChange: (v: ImapFormValues) => void;
  passwordHint?: string;
  idPrefix: string;
  allowedPorts: number[];
}) {
  const set = (k: keyof ImapFormValues) => (e: ChangeEvent<HTMLInputElement>) =>
    onChange({ ...values, [k]: e.target.value });
  return (
    <>
      <label className="field">
        Bezeichnung
        <input
          className="input"
          type="text"
          name="label"
          autoComplete="off"
          maxLength={80}
          required
          value={values.label}
          onChange={set("label")}
          placeholder="z. B. Privat"
        />
      </label>
      <div className="grid-host">
        <label className="field">
          Server
          <input
            className="input mono"
            type="text"
            name="host"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            inputMode="url"
            maxLength={253}
            required
            value={values.host}
            onChange={set("host")}
            placeholder="mail.example.org"
          />
        </label>
        <label className="field">
          Port
          <input
            className="input mono"
            type="text"
            name="port"
            inputMode="numeric"
            autoComplete="off"
            maxLength={5}
            required
            value={values.port}
            onChange={(e) =>
              onChange({ ...values, port: e.target.value.replace(/\D/g, "") })
            }
            aria-describedby={
              allowedPorts.length ? `${idPrefix}-ports` : undefined
            }
          />
        </label>
      </div>
      {allowedPorts.length ? (
        <span id={`${idPrefix}-ports`} className="muted small field-hint">
          Erlaubte Ports: {allowedPorts.join(", ")} (IMAP über TLS)
        </span>
      ) : null}
      <label className="field">
        Benutzer
        <input
          className="input"
          type="email"
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={254}
          required
          value={values.username}
          onChange={set("username")}
          placeholder="name@example.org"
        />
      </label>
      <div className="field">
        <label htmlFor={`${idPrefix}-pw`}>App-Passwort</label>
        <PasswordInput
          id={`${idPrefix}-pw`}
          className="input"
          name="password"
          autoComplete="new-password"
          maxLength={1024}
          value={values.password}
          onChange={set("password")}
        />
        {passwordHint ? (
          <span className="muted small field-hint">{passwordHint}</span>
        ) : null}
      </div>
    </>
  );
}

function validPort(port: string): number | null {
  const n = Number(port);
  return Number.isInteger(n) && n >= 1 && n <= 65535 ? n : null;
}

function AddImapCard({
  allowedPorts,
  onAdded,
}: {
  allowedPorts: number[];
  onAdded: (a: Account) => void;
}) {
  const idPrefix = useId();
  const empty: ImapFormValues = {
    label: "Postfach",
    host: "",
    port: String(allowedPorts[0] ?? 993),
    username: "",
    password: "",
  };
  const [values, setValues] = useState<ImapFormValues>(empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const port = validPort(values.port);
    if (
      !values.label.trim() ||
      !values.host.trim() ||
      !values.username.trim() ||
      !values.password
    ) {
      setError("Bitte alle Felder ausfüllen.");
      return;
    }
    if (!port) {
      setError("Bitte einen gültigen Port angeben.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const acc = await ep.addImapAccount({
        label: values.label.trim(),
        host: values.host.trim(),
        port,
        username: values.username.trim(),
        password: values.password,
      });
      setValues(empty);
      onAdded(acc);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`${idPrefix}-h`} className="card conn-card">
      <div className="conn-head">
        <div className="stack-2">
          <h2 id={`${idPrefix}-h`}>Postfach hinzufügen</h2>
          <span className="muted small">IMAP über TLS</span>
        </div>
      </div>
      <form className="stack-18" onSubmit={submit} noValidate>
        <ImapFields
          values={values}
          onChange={setValues}
          idPrefix={idPrefix}
          allowedPorts={allowedPorts}
        />
        <div className="check-list">
          <span>
            <Icon
              name="check"
              size={16}
              strokeWidth={2.2}
              className="text-green"
            />
            Zertifikat wird geprüft
          </span>
          <span>
            <Icon
              name="check"
              size={16}
              strokeWidth={2.2}
              className="text-green"
            />
            TLS-Verbindung, keine unverschlüsselte Rückfallebene
          </span>
        </div>
        {error ? <ErrorBox>{error}</ErrorBox> : null}
        <div className="row-wrap">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Verbindung wird geprüft …" : "Verbinden & speichern"}
          </button>
        </div>
      </form>
    </section>
  );
}

function ImapHelpCard() {
  const idPrefix = useId();
  return (
    <section
      aria-labelledby={`${idPrefix}-h`}
      className="card conn-card help-card"
    >
      <div className="stack-2">
        <h2 id={`${idPrefix}-h`}>Was trage ich ein?</h2>
        <span className="muted small">
          Die Daten findest du bei deinem Mail-Anbieter, meist unter „IMAP“ oder
          „E-Mail-Programme“.
        </span>
      </div>
      <dl className="help-list">
        <div>
          <dt>Bezeichnung</dt>
          <dd>Ein Name nur für dich, z. B. „Privat“ oder „Arbeit“.</dd>
        </div>
        <div>
          <dt>Server</dt>
          <dd>
            Der Name deines Mailservers, meist{" "}
            <span className="mono">mail.deine-domain.at</span> – ohne https://
            davor.
          </dd>
        </div>
        <div>
          <dt>Port</dt>
          <dd>
            <span className="mono">993</span> – IMAP über TLS. Quitly verbindet
            sich nie unverschlüsselt.
          </dd>
        </div>
        <div>
          <dt>Benutzer</dt>
          <dd>Deine vollständige E-Mail-Adresse.</dd>
        </div>
        <div>
          <dt>App-Passwort</dt>
          <dd>
            Dein Passwort oder – falls dein Anbieter das anbietet – ein eigenes
            App-Passwort mit IMAP-Recht. Ein App-Passwort kannst du jederzeit
            widerrufen, ohne dein Hauptpasswort zu ändern.
          </dd>
        </div>
      </dl>
    </section>
  );
}

function AccountCard({
  account,
  allowedPorts,
  onChanged,
  onRemove,
  scanning,
  onScan,
  onCancelScan,
}: {
  account: Account;
  allowedPorts: number[];
  onChanged: (a: Account) => void;
  onRemove: (a: Account) => void;
  scanning: boolean;
  onScan: () => void;
  onCancelScan: () => void;
}) {
  const idPrefix = useId();
  const [busy, setBusy] = useState<null | "test" | "save">(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<ImapFormValues>({
    label: "",
    host: "",
    port: "",
    username: "",
    password: "",
  });

  function openEdit() {
    setValues({
      label: account.label,
      host: account.imap_host ?? "",
      port: String(account.imap_port ?? 993),
      username: account.email_address ?? "",
      password: "",
    });
    setError(null);
    setInfo(null);
    setEditing(true);
  }

  async function test() {
    setBusy("test");
    setError(null);
    setInfo(null);
    try {
      const a = await ep.testAccount(account.id);
      onChanged(a);
      setInfo(a.status === "ok" ? "Verbindung erfolgreich." : null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const port = validPort(values.port);
    if (!port) {
      setError("Bitte einen gültigen Port angeben.");
      return;
    }
    const body: Partial<ep.ImapInput> = {};
    if (values.label.trim() && values.label.trim() !== account.label)
      body.label = values.label.trim();
    if (values.host.trim() && values.host.trim() !== account.imap_host)
      body.host = values.host.trim();
    if (port !== account.imap_port) body.port = port;
    if (
      values.username.trim() &&
      values.username.trim() !== account.email_address
    )
      body.username = values.username.trim();
    if (values.password) body.password = values.password;
    setBusy("save");
    setError(null);
    try {
      const a = await ep.updateImapAccount(account.id, body);
      onChanged(a);
      setEditing(false);
      setInfo("Gespeichert und Verbindung geprüft.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby={`${idPrefix}-h`} className="card conn-card">
      <div className="conn-head">
        <div className="stack-2 min-0">
          <h2 id={`${idPrefix}-h`} className="truncate">
            {account.label}
          </h2>
          <span className="muted small">IMAP über TLS</span>
        </div>
        {account.status === "ok" ? (
          <span className="pill pill-green">
            <span className="dot dot-green" aria-hidden="true" />
            Verbunden
          </span>
        ) : (
          <span className="pill pill-red">
            <span className="dot dot-red" aria-hidden="true" />
            Fehler
          </span>
        )}
      </div>

      <dl className="kv">
        <dt>Adresse</dt>
        <dd className="break">{account.email_address || "—"}</dd>
        <dt>Server</dt>
        <dd className="mono break">
          {account.imap_host}:{account.imap_port}
        </dd>
        <dt>Letzter Scan</dt>
        <dd>
          {account.last_scan_at
            ? formatDateTime(account.last_scan_at)
            : "Noch nie"}
        </dd>
      </dl>

      {account.status === "error" && account.last_error ? (
        <ErrorBox>{account.last_error}</ErrorBox>
      ) : null}
      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {info ? (
        <p className="text-green small no-margin" role="status">
          {info}
        </p>
      ) : null}

      {editing ? (
        <form className="stack-18 edit-form" onSubmit={save} noValidate>
          <ImapFields
            values={values}
            onChange={setValues}
            idPrefix={idPrefix}
            allowedPorts={allowedPorts}
            passwordHint="Gespeichert und verschlüsselt. Leer lassen, um das bisherige Passwort zu behalten."
          />
          <div className="row-wrap">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy !== null}
            >
              {busy === "save" ? "Wird geprüft …" : "Speichern"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setEditing(false)}
              disabled={busy !== null}
            >
              Abbrechen
            </button>
          </div>
        </form>
      ) : (
        <div className="row-wrap push-bottom">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void test()}
            disabled={busy !== null}
          >
            {busy === "test" ? "Wird getestet …" : "Verbindung testen"}
          </button>
          {scanning ? (
            <button
              type="button"
              className="btn btn-secondary text-red"
              onClick={onCancelScan}
            >
              Scan abbrechen
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={onScan}>
              Scan starten
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={openEdit}
          >
            Bearbeiten
          </button>
          <button
            type="button"
            className="btn btn-danger-text push-right"
            onClick={() => onRemove(account)}
          >
            Entfernen
          </button>
        </div>
      )}
    </section>
  );
}

function RemoveDialog({
  account,
  onCancel,
  onRemoved,
}: {
  account: Account;
  onCancel: () => void;
  onRemoved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await ep.removeAccount(account.id);
      onRemoved();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <Modal
      onClose={onCancel}
      labelledBy="remove-title"
      describedBy="remove-desc"
      busy={busy}
      initialFocus={cancelRef}
    >
      <div className="dialog-head">
        <span className="dialog-icon dialog-icon-red" aria-hidden="true">
          <Icon name="alert" size={20} strokeWidth={2} />
        </span>
        <h2 id="remove-title">Postfach „{account.label}“ entfernen?</h2>
      </div>
      <p id="remove-desc" className="muted no-margin">
        Quitly löscht die gespeicherten Zugangsdaten. Deine E-Mails auf dem
        Server bleiben unverändert.
      </p>
      {error ? <ErrorBox>{error}</ErrorBox> : null}
      <div className="dialog-actions">
        <button
          ref={cancelRef}
          type="button"
          className="btn btn-secondary"
          onClick={onCancel}
          disabled={busy}
        >
          Abbrechen
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => void confirm()}
          disabled={busy}
        >
          {busy ? "Wird entfernt …" : "Entfernen"}
        </button>
      </div>
    </Modal>
  );
}

export function ConnectionsPage() {
  const scans = useScans();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{
    kind: "success" | "error" | "info";
    text: string;
  } | null>(null);
  const [removing, setRemoving] = useState<Account | null>(null);
  const [since, setSince] = useState("");
  const [scanError, setScanError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [acc, cfg] = await Promise.all([ep.getAccounts(), ep.getConfig()]);
      setAccounts(acc);
      setConfig(cfg);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const lastVersion = useRef(scans.finishedVersion);
  useEffect(() => {
    if (scans.finishedVersion !== lastVersion.current) {
      lastVersion.current = scans.finishedVersion;
      void load();
    }
  }, [scans.finishedVersion, load]);

  const list = accounts ?? [];
  const allowedPorts = config?.imap_allowed_ports ?? [];
  const sinceDays = since ? Number(since) : undefined;

  async function scan(ids: number[]) {
    setScanError(null);
    const errors = await scans.start(ids, sinceDays);
    if (errors.length) setScanError(errors.join(" "));
  }

  function replaceAccount(a: Account) {
    setAccounts((prev) => prev?.map((x) => (x.id === a.id ? a : x)) ?? prev);
  }

  return (
    <div className="page">
      <PageHeader
        title="Verbindungen"
        intro="Verbinde deine Postfächer. Zugangsdaten werden verschlüsselt gespeichert, nie im Klartext und nie im Protokoll."
      />

      {notice ? (
        <Banner kind={notice.kind} onClose={() => setNotice(null)}>
          {notice.text}
        </Banner>
      ) : null}
      {loadError ? (
        <Banner kind="error" title="Daten konnten nicht geladen werden">
          {loadError}{" "}
          <button
            type="button"
            className="link-btn"
            onClick={() => void load()}
          >
            Erneut versuchen
          </button>
        </Banner>
      ) : null}

      {accounts === null && !loadError ? <Spinner /> : null}

      {accounts !== null ? (
        <>
          {list.length ? (
            <section aria-label="Verbundene Postfächer" className="conn-grid">
              {list.map((a) => {
                const job = scans.jobs[a.id];
                return (
                  <AccountCard
                    key={a.id}
                    account={a}
                    allowedPorts={allowedPorts}
                    onChanged={replaceAccount}
                    onRemove={setRemoving}
                    scanning={isActive(job)}
                    onScan={() => void scan([a.id])}
                    onCancelScan={() => job && void scans.cancel(job.id)}
                  />
                );
              })}
            </section>
          ) : null}

          <div className="conn-grid">
            <AddImapCard
              allowedPorts={allowedPorts}
              onAdded={(a) => {
                setAccounts((prev) => [...(prev ?? []), a]);
                setNotice({
                  kind: "success",
                  text: `„${a.label}“ wurde verbunden. Starte jetzt einen Scan.`,
                });
              }}
            />
            <ImapHelpCard />
          </div>

          <section aria-labelledby="scan-h" className="card scan-card">
            <div className="scan-card-head">
              <div className="stack-4">
                <h2 id="scan-h">Konten-Scan</h2>
                <span className="muted">
                  Quitly liest Absender, Betreff, Datum und den Anfang des
                  Textes, um Konten zu erkennen. Inhalte werden nicht
                  gespeichert, Anhänge nie geöffnet.
                </span>
              </div>
              <div className="row-wrap align-end">
                <label className="field-compact">
                  Zeitraum
                  <select
                    className="select"
                    value={since}
                    onChange={(e) => setSince(e.target.value)}
                    disabled={scans.anyActive}
                  >
                    {SINCE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                {scans.anyActive ? (
                  <button
                    type="button"
                    className="btn btn-secondary text-red"
                    onClick={() => void scans.cancelAll()}
                  >
                    Scan abbrechen
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={!list.length}
                    onClick={() => void scan(list.map((a) => a.id))}
                  >
                    Scan starten
                  </button>
                )}
              </div>
            </div>
            {!list.length ? (
              <p className="muted no-margin">Verbinde zuerst ein Postfach.</p>
            ) : null}
            {scanError ? <ErrorBox>{scanError}</ErrorBox> : null}
            <ScanProgressList
              jobs={scans.jobs}
              accounts={list}
              onCancel={(id) => void scans.cancel(id)}
            />
          </section>
        </>
      ) : null}

      {removing ? (
        <RemoveDialog
          account={removing}
          onCancel={() => setRemoving(null)}
          onRemoved={() => {
            const removed = removing;
            setRemoving(null);
            scans.clear(removed.id);
            setAccounts(
              (prev) => prev?.filter((x) => x.id !== removed.id) ?? prev,
            );
            setNotice({
              kind: "info",
              text: `„${removed.label}“ wurde entfernt.`,
            });
          }}
        />
      ) : null}
    </div>
  );
}
