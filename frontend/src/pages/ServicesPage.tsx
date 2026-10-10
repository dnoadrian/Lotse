// „Konten“: aus den Postfächern erkannte Dienste (Main.dc.html / Mobile.dc.html).
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Account, AppConfig, Service, ServiceStatus } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { ScanProgressList } from "../components/ScanProgress";
import { Banner, PageHeader, Spinner, useIsPhone } from "../components/ui";
import { formatDateTime, formatLooseDate, formatNumber } from "../lib/format";
import {
  deletionBadge,
  STATUS_META,
  type LinkFilter,
  type QualityFilter,
  type StatusFilter,
  confidencePercent,
  difficultyMeta,
  filterServices,
  mergedSendersNote,
  qualityMeta,
  signalSummary,
  statusCounts,
} from "../lib/mappings";
import { isActive, useScans } from "../lib/scans";
import { isSafeHttpUrl } from "../lib/url";
import { ServiceDetail } from "./ServiceDetail";
import { ServiceIcon } from "../components/ServiceIcon";
import { StatusSelect } from "./StatusSelect";

const CHIPS: { value: StatusFilter; label: string }[] = [
  { value: "alle", label: "Alle" },
  { value: "offen", label: "Offen" },
  { value: "angefragt", label: "Angefragt" },
  { value: "geloescht", label: "Gelöscht" },
  { value: "behalten", label: "Behalten" },
];

function LifecycleHints({
  services,
  onStatus,
  onOpen,
}: {
  services: Service[];
  onStatus: (s: Service, status: ServiceStatus) => void;
  onOpen: (id: number) => void;
}) {
  const hints = services
    .filter(
      (s) => s.lifecycle === "likely_deleted" || s.lifecycle === "still_active",
    )
    .slice(0, 6);
  if (!hints.length) return null;
  return (
    <section aria-label="Hinweise zu Löschanfragen" className="hint-list">
      {hints.map((s) => (
        <div key={s.id} className="hint-card">
          <ServiceIcon id={s.id} name={s.name} />
          {s.lifecycle === "likely_deleted" ? (
            <p className="no-margin">
              <strong>{s.name}</strong>: Seit 14 Tagen keine Mail mehr nach
              deiner Löschanfrage. Wurde das Konto gelöscht?
            </p>
          ) : (
            <p className="no-margin">
              <strong>{s.name}</strong> schickt nach deiner Löschanfrage weiter
              Konto-Mails – das Konto scheint noch aktiv.
            </p>
          )}
          <div className="hint-actions">
            {s.lifecycle === "likely_deleted" ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => onStatus(s, "geloescht")}
                >
                  Ja, gelöscht
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onStatus(s, "offen")}
                >
                  Noch aktiv
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => onOpen(s.id)}
              >
                Details ansehen
              </button>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

function isInteractiveTarget(e: MouseEvent): boolean {
  const el = e.target as HTMLElement;
  return !!el.closest("a, button, input, select, label, textarea");
}

function DeleteLink({
  service,
  block = false,
}: {
  service: Service;
  block?: boolean;
}) {
  const url = service.jdm?.url;
  if (service.jdm && isSafeHttpUrl(url)) {
    return (
      <a
        className={`btn btn-secondary btn-sm btn-link-blue${block ? " btn-grow" : ""}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Löschseite von ${service.name} öffnen (neues Fenster)`}
      >
        Löschseite öffnen
        <Icon name="external" size={14} strokeWidth={2} />
      </a>
    );
  }
  return (
    <span className={block ? "no-jdm-block" : "no-jdm muted small"}>
      {service.jdm ? "Kein Löschlink" : "Kein JDM-Eintrag"}
    </span>
  );
}

function OpenLinksDialog({
  services,
  onClose,
}: {
  services: Service[];
  onClose: () => void;
}) {
  const withLink = services.filter((s) => s.jdm && isSafeHttpUrl(s.jdm.url));
  const without = services.filter((s) => !(s.jdm && isSafeHttpUrl(s.jdm.url)));
  return (
    <Modal onClose={onClose} labelledBy="links-title" describedBy="links-desc">
      <div className="dialog-head">
        <h2 id="links-title">Löschseiten öffnen</h2>
      </div>
      <p id="links-desc" className="muted no-margin">
        Browser blockieren mehrere Fenster auf einmal. Öffne die Löschseiten
        einzeln – jede in einem neuen Tab.
      </p>
      {withLink.length ? (
        <ul className="link-list">
          {withLink.map((s) => (
            <li key={s.id}>
              <span className="link-list-name">
                <span className="strong">{s.name}</span>
                <span
                  className={`small tone-${difficultyMeta(s.jdm?.difficulty).tone}`}
                >
                  {difficultyMeta(s.jdm?.difficulty).label}
                </span>
              </span>
              <a
                className="btn btn-secondary btn-sm btn-link-blue"
                href={s.jdm!.url!}
                target="_blank"
                rel="noopener noreferrer"
              >
                Öffnen <Icon name="external" size={14} strokeWidth={2} />
                <span className="sr-only"> – {s.name}</span>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="no-margin">
          Keiner der ausgewählten Dienste hat einen Löschlink.
        </p>
      )}
      {without.length ? (
        <p className="muted small no-margin">
          Ohne Löschlink: {without.map((s) => s.name).join(", ")}
        </p>
      ) : null}
      <div className="dialog-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          Schließen
        </button>
      </div>
    </Modal>
  );
}

export function ServicesPage() {
  const scans = useScans();
  const isPhone = useIsPhone();
  const [services, setServices] = useState<Service[] | null>(null);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);

  const [query, setQuery] = useState("");
  const [statusF, setStatusF] = useState<StatusFilter>("alle");
  const [qualityF, setQualityF] = useState<QualityFilter>("alle");
  const [linkF, setLinkF] = useState<LinkFilter>("alle");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detailId, setDetailId] = useState<number | null>(null);
  const [linksOpen, setLinksOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  const [params, setParams] = useSearchParams();
  const mailboxF = Number(params.get("postfach")) || null;
  const shiftDown = useRef(false);
  const lastToggled = useRef<number | null>(null);

  // Shift gedrückt halten → Bereich auswählen (wie in Mailprogrammen)
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "Shift") shiftDown.current = true;
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === "Shift") shiftDown.current = false;
    };
    const blur = () => {
      shiftDown.current = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  function chooseMailbox(id: number | null) {
    const next = new URLSearchParams(params);
    if (id) next.set("postfach", String(id));
    else next.delete("postfach");
    setParams(next, { replace: true });
    setSelected(new Set());
    lastToggled.current = null;
  }

  const load = useCallback(async () => {
    try {
      const [svc, acc] = await Promise.all([
        ep.getServices(),
        ep.getAccounts(),
      ]);
      setServices(svc);
      setAccounts(acc);
      setLoadError(null);
      const ids = new Set(svc.map((s) => s.id));
      setSelected((prev) => new Set([...prev].filter((id) => ids.has(id))));
    } catch (err) {
      setLoadError(errorText(err));
    }
    try {
      setConfig(await ep.getConfig());
    } catch {
      /* Datenstand ist optional */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Nach jedem abgeschlossenen Scan Daten neu laden
  const lastVersion = useRef(scans.finishedVersion);
  useEffect(() => {
    if (scans.finishedVersion !== lastVersion.current) {
      lastVersion.current = scans.finishedVersion;
      void load();
    }
  }, [scans.finishedVersion, load]);

  const allServices = services ?? [];
  // Nur die Konten eines Postfachs zeigen (oder alle)
  const all = useMemo(() => {
    if (!mailboxF) return allServices;
    // Nur dieses Postfach: Quelle, Mail- und Absenderzahl beziehen sich dann ausschließlich darauf
    return allServices.flatMap((s) => {
      const src = s.sources.find((x) => x.account_id === mailboxF);
      if (!src) return [];
      return [
        {
          ...s,
          sources: [src],
          message_count: src.messages,
          signal_count: src.signals,
          sender_count: src.senders ?? s.sender_count,
        },
      ];
    });
  }, [allServices, mailboxF]);
  const visible = useMemo(
    () =>
      filterServices(all, {
        query,
        status: statusF,
        quality: qualityF,
        link: linkF,
      }),
    [all, query, statusF, qualityF, linkF],
  );
  const counts = useMemo(() => statusCounts(all), [all]);
  const detail =
    detailId !== null ? (all.find((s) => s.id === detailId) ?? null) : null;
  const selectedServices = all.filter((s) => selected.has(s.id));
  const allVisibleChecked =
    visible.length > 0 && visible.every((s) => selected.has(s.id));
  const someVisibleChecked = visible.some((s) => selected.has(s.id));

  const headCheckRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (headCheckRef.current)
      headCheckRef.current.indeterminate =
        someVisibleChecked && !allVisibleChecked;
  }, [someVisibleChecked, allVisibleChecked]);

  const accountList = accounts ?? [];
  const activeJobs = Object.values(scans.jobs).filter(
    (j) => isActive(j) && accountList.some((a) => a.id === j.account_id),
  );
  const lastScan = accountList
    .map((a) => a.last_scan_at)
    .filter((x): x is string => !!x)
    .sort()
    .pop();
  const failedJobs = Object.values(scans.jobs).filter(
    (j) =>
      j.status === "error" && accountList.some((a) => a.id === j.account_id),
  );

  async function changeStatus(s: Service, status: ServiceStatus) {
    const before = s.status;
    setServices(
      (list) =>
        list?.map((x) => (x.id === s.id ? { ...x, status } : x)) ?? null,
    );
    try {
      const updated = await ep.setServiceStatus(s.id, status);
      setServices(
        (list) => list?.map((x) => (x.id === s.id ? updated : x)) ?? null,
      );
    } catch (err) {
      setServices(
        (list) =>
          list?.map((x) => (x.id === s.id ? { ...x, status: before } : x)) ??
          null,
      );
      setNotice({
        kind: "error",
        text: `Status für ${s.name} nicht gespeichert: ${errorText(err)}`,
      });
    }
  }

  async function bulk(status: ServiceStatus) {
    const ids = [...selected];
    if (!ids.length) return;
    setBulkBusy(true);
    try {
      const res = await ep.bulkServiceStatus(ids, status);
      const idSet = new Set(ids);
      setServices(
        (list) =>
          list?.map((x) => (idSet.has(x.id) ? { ...x, status } : x)) ?? null,
      );
      setSelected(new Set());
      setNotice({
        kind: "success",
        text: `${formatNumber(res.updated)} ${res.updated === 1 ? "Dienst" : "Dienste"} auf „${STATUS_META[status].label}“ gesetzt.`,
      });
    } catch (err) {
      setNotice({ kind: "error", text: errorText(err) });
      void load();
    } finally {
      setBulkBusy(false);
    }
  }

  async function rescan() {
    if (!accountList.length) return;
    setScanBusy(true);
    const errors = await scans.start(accountList.map((a) => a.id));
    setScanBusy(false);
    if (errors.length) setNotice({ kind: "error", text: errors.join(" ") });
  }

  function toggle(id: number) {
    const from = lastToggled.current;
    const range = shiftDown.current && from !== null && from !== id;
    setSelected((prev) => {
      const next = new Set(prev);
      const select = !prev.has(id);
      if (range) {
        const ids = visible.map((s) => s.id);
        const a = ids.indexOf(from);
        const b = ids.indexOf(id);
        if (a !== -1 && b !== -1) {
          for (const x of ids.slice(Math.min(a, b), Math.max(a, b) + 1)) {
            if (select) next.add(x);
            else next.delete(x);
          }
          return next;
        }
      }
      if (select) next.add(id);
      else next.delete(id);
      return next;
    });
    lastToggled.current = id;
  }

  function toggleAllVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const s of visible) {
        if (allVisibleChecked) next.delete(s.id);
        else next.add(s.id);
      }
      return next;
    });
  }

  const tiles = [
    { label: "Erkannte Konten", value: all.length, tone: "" },
    {
      label: "Mit Löschanleitung",
      value: all.filter((s) => s.jdm).length,
      tone: "",
    },
    { label: "Löschung angefragt", value: counts.angefragt, tone: "tone-link" },
    { label: "Gelöscht", value: counts.geloescht, tone: "tone-green" },
  ];

  const scanButton = (
    <button
      type="button"
      className="btn btn-primary"
      onClick={() => void rescan()}
      disabled={scanBusy || scans.anyActive || !accountList.length}
    >
      <Icon name="refresh" size={16} strokeWidth={2.2} />
      {scans.anyActive ? "Scan läuft …" : "Neu scannen"}
    </button>
  );

  const header = (
    <PageHeader
      title="Konten"
      intro="Aus deinen E-Mails erkannte Dienste, zusammengeführt und mit den Löschanleitungen von JustDeleteMe abgeglichen."
      actions={
        <>
          <a className="btn btn-secondary" href={ep.EXPORT_CSV_URL} download>
            CSV exportieren
          </a>
          {scanButton}
        </>
      }
    />
  );

  if (loadError && services === null) {
    return (
      <div className="page">
        {header}
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
      </div>
    );
  }

  if (services === null || accounts === null) {
    return (
      <div className="page">
        {header}
        <Spinner />
      </div>
    );
  }

  return (
    <div className="page">
      {header}

      {notice ? (
        <Banner kind={notice.kind} onClose={() => setNotice(null)}>
          {notice.text}
        </Banner>
      ) : null}

      <div className="status-line">
        {activeJobs.length ? (
          <span className="status-line-main">
            <span className="dot dot-accent" aria-hidden="true" />
            Scan läuft ({activeJobs.length}{" "}
            {activeJobs.length === 1 ? "Postfach" : "Postfächer"})
          </span>
        ) : failedJobs.length ? (
          <span className="status-line-main">
            <span className="dot dot-red" aria-hidden="true" />
            Letzter Scan mit Fehlern
          </span>
        ) : lastScan ? (
          <span className="status-line-main">
            <span className="dot dot-green" aria-hidden="true" />
            Letzter Scan abgeschlossen · {formatDateTime(lastScan)}
          </span>
        ) : (
          <span className="status-line-main">
            <span className="dot dot-muted" aria-hidden="true" />
            Noch kein Scan
          </span>
        )}
        {accountList.map((a) => (
          <span key={a.id}>
            {a.label} · IMAP
            {a.status === "error" ? (
              <span className="text-red"> (Fehler)</span>
            ) : null}
          </span>
        ))}
        {config ? (
          <span className="mono">
            JDM-Datenstand {formatLooseDate(config.jdm.date)} ·{" "}
            {formatNumber(config.jdm.entries)} Einträge
          </span>
        ) : null}
      </div>

      {activeJobs.length ? (
        <ScanProgressList
          jobs={scans.jobs}
          accounts={accountList}
          onlyActive
          onCancel={(id) => void scans.cancel(id)}
        />
      ) : null}

      {accountList.length === 0 ? (
        <div className="empty-card">
          <h2>Noch kein Postfach verbunden</h2>
          <p className="muted">
            Verbinde dein Postfach (IMAP). Quitly liest Kopfzeilen und den
            Anfang jeder Mail und erkennt daraus, bei welchen Diensten du ein
            Konto hast.
          </p>
          <Link className="btn btn-primary" to="/verbindungen">
            Postfach verbinden
          </Link>
        </div>
      ) : (
        <>
          <section aria-label="Übersicht" className="tiles">
            {tiles.map((t) => (
              <div key={t.label} className="tile">
                <span className="tile-label">{t.label}</span>
                <span className={`tile-value ${t.tone}`}>
                  {formatNumber(t.value)}
                </span>
              </div>
            ))}
          </section>

          <LifecycleHints
            services={all}
            onStatus={(sv, st) => void changeStatus(sv, st)}
            onOpen={setDetailId}
          />

          {all.length === 0 ? (
            <div className="empty-card">
              <h2>Noch keine Konten erkannt</h2>
              <p className="muted">
                Starte einen Scan, damit Quitly deine Postfächer nach
                Registrierungs-Mails durchsucht.
              </p>
              {scanButton}
            </div>
          ) : (
            <section aria-label="Kontoliste" className="stack-14">
              <div className="toolbar">
                <label className="search">
                  <Icon
                    name="search"
                    size={16}
                    strokeWidth={2}
                    className="muted-icon"
                  />
                  <span className="sr-only">Dienste durchsuchen</span>
                  <input
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Dienst oder Domain suchen …"
                  />
                </label>
                <div
                  role="group"
                  aria-label="Nach Status filtern"
                  className={`chips${isPhone ? " chips-scroll" : ""}`}
                >
                  {CHIPS.map((c) => (
                    <button
                      key={c.value}
                      type="button"
                      className="chip"
                      aria-pressed={statusF === c.value}
                      onClick={() => setStatusF(c.value)}
                    >
                      {c.label}
                      <span className="chip-count">{counts[c.value]}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="toolbar toolbar-secondary">
                {accountList.length > 1 ? (
                  <label className="inline-select">
                    <span>Postfach</span>
                    <select
                      value={mailboxF ?? ""}
                      onChange={(e) => chooseMailbox(Number(e.target.value) || null)}
                    >
                      <option value="">Alle Postfächer</option>
                      {accountList.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.label}
                          {a.email_address && a.email_address !== a.label ? ` (${a.email_address})` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label className="inline-select">
                  <span>Erkennung</span>
                  <select
                    value={qualityF}
                    onChange={(e) =>
                      setQualityF(e.target.value as QualityFilter)
                    }
                  >
                    <option value="alle">Alle</option>
                    <option value="hoch">Hoch</option>
                    <option value="mittel">Mittel</option>
                    <option value="niedrig">Niedrig</option>
                  </select>
                </label>
                <label className="inline-select">
                  <span>Löschlink</span>
                  <select
                    value={linkF}
                    onChange={(e) => setLinkF(e.target.value as LinkFilter)}
                  >
                    <option value="alle">Alle</option>
                    <option value="mit">Mit Löschlink</option>
                    <option value="ohne">Ohne Löschlink</option>
                  </select>
                </label>
                <span className="muted small toolbar-count" aria-live="polite">
                  {visible.length === all.length
                    ? `${formatNumber(all.length)} Dienste`
                    : `${formatNumber(visible.length)} von ${formatNumber(all.length)} Diensten`}
                </span>
              </div>

              {selected.size > 0 ? (
                <div
                  className="bulk-bar"
                  role="region"
                  aria-label="Aktionen für Auswahl"
                >
                  <span className="bulk-count">{selected.size} ausgewählt</span>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setLinksOpen(true)}
                  >
                    Löschseiten öffnen
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm tone-link"
                    disabled={bulkBusy}
                    onClick={() => void bulk("angefragt")}
                  >
                    Als angefragt markieren
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm tone-green"
                    disabled={bulkBusy}
                    onClick={() => void bulk("geloescht")}
                  >
                    Als gelöscht markieren
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm tone-muted"
                    disabled={bulkBusy}
                    onClick={() => void bulk("behalten")}
                  >
                    Behalten
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm bulk-clear"
                    onClick={() => setSelected(new Set())}
                  >
                    Auswahl aufheben
                  </button>
                </div>
              ) : null}

              {isPhone ? (
                <div className="svc-cards">
                  {visible.length > 0 ? (
                    <label className="check-row">
                      <input
                        ref={headCheckRef}
                        type="checkbox"
                        checked={allVisibleChecked}
                        onChange={toggleAllVisible}
                      />
                      Alle sichtbaren auswählen
                    </label>
                  ) : null}
                  {visible.map((s) => {
                    const pct = confidencePercent(s.confidence);
                    return (
                      <article
                        key={s.id}
                        className={`svc-card${selected.has(s.id) ? " selected" : ""}`}
                      >
                        <div className="svc-card-head">
                          <label className="check-cell">
                            <input
                              type="checkbox"
                              checked={selected.has(s.id)}
                              onChange={() => toggle(s.id)}
                              aria-label={`${s.name} auswählen`}
                            />
                          </label>
                          <ServiceIcon id={s.id} name={s.name} />
                          <div className="svc-card-title">
                            <button
                              type="button"
                              className="name-btn"
                              onClick={() => setDetailId(s.id)}
                            >
                              {s.name}
                            </button>
                            <span className="muted mono small truncate">
                              {s.domains[0] ?? "—"} · {pct} %
                            </span>
                          </div>
                          <span className="status-pill" data-status={s.status}>
                            {STATUS_META[s.status]?.label ?? s.status}
                          </span>
                        </div>
                        {s.deletion_detected ? (
                          <span className="badge badge-green self-start">
                            {deletionBadge(s)}
                          </span>
                        ) : null}
                        <div className="svc-card-actions">
                          <DeleteLink service={s} block />
                          <StatusSelect
                            service={s}
                            onChange={(sv, st) => void changeStatus(sv, st)}
                            compact
                          />
                        </div>
                      </article>
                    );
                  })}
                  {visible.length === 0 ? (
                    <div className="empty-row">
                      Keine Konten passen zu Suche und Filter.
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="table-box">
                  <div
                    className="svc-table"
                    role="table"
                    aria-label="Erkannte Dienste"
                  >
                    <div className="svc-row svc-head" role="row">
                      <label className="check-cell" role="columnheader">
                        <input
                          ref={headCheckRef}
                          type="checkbox"
                          checked={allVisibleChecked}
                          onChange={toggleAllVisible}
                          aria-label="Alle sichtbaren auswählen"
                        />
                      </label>
                      <span role="columnheader">Dienst</span>
                      <span role="columnheader">Quelle</span>
                      <span role="columnheader">Erkennung</span>
                      <span role="columnheader">Aufwand</span>
                      <span role="columnheader">Status</span>
                      <span role="columnheader" className="align-right">
                        Löschen
                      </span>
                    </div>
                    {visible.map((s) => {
                      const q = qualityMeta(s.quality);
                      const pct = confidencePercent(s.confidence);
                      const d = difficultyMeta(s.jdm?.difficulty);
                      const extraDomains =
                        s.domains.length > 1 ? ` +${s.domains.length - 1}` : "";
                      return (
                        <div
                          key={s.id}
                          role="row"
                          className={`svc-row svc-body-row${selected.has(s.id) ? " selected" : ""}`}
                          onClick={(e) => {
                            if (!isInteractiveTarget(e)) setDetailId(s.id);
                          }}
                        >
                          <label className="check-cell" role="cell">
                            <input
                              type="checkbox"
                              checked={selected.has(s.id)}
                              onChange={() => toggle(s.id)}
                              aria-label={`${s.name} auswählen`}
                            />
                          </label>
                          <div className="svc-name-cell" role="cell">
                            <ServiceIcon id={s.id} name={s.name} />
                            <div className="svc-name-text">
                              <span className="svc-name-line">
                                <button
                                  type="button"
                                  className="name-btn"
                                  onClick={() => setDetailId(s.id)}
                                  aria-label={`Details zu ${s.name}`}
                                >
                                  {s.name}
                                </button>
                                {s.deletion_detected ? (
                                  <span className="badge badge-green">
                                    {deletionBadge(s)}
                                  </span>
                                ) : null}
                              </span>
                              <span className="muted mono small truncate">
                                {(s.domains[0] ?? "—") + extraDomains} ·{" "}
                                {formatNumber(s.message_count)} Mails
                                {mergedSendersNote(s.sender_count)}
                              </span>
                            </div>
                          </div>
                          <span className="muted svc-source" role="cell">
                            {s.sources.length
                              ? s.sources.map((x) => x.label).join(", ")
                              : "—"}
                          </span>
                          <div className="quality" role="cell">
                            <div className="quality-head">
                              <span>{q.label}</span>
                              <span className="mono muted">{pct} %</span>
                            </div>
                            <div className="bar" aria-hidden="true">
                              <div
                                className={`bar-fill ${q.barClass}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="muted small">
                              {signalSummary(s.signals)}
                            </span>
                          </div>
                          <span className={`small tone-${d.tone}`} role="cell">
                            {d.label}
                          </span>
                          <div role="cell">
                            <StatusSelect
                              service={s}
                              onChange={(sv, st) => void changeStatus(sv, st)}
                            />
                          </div>
                          <div className="align-right" role="cell">
                            <DeleteLink service={s} />
                          </div>
                        </div>
                      );
                    })}
                    {visible.length === 0 ? (
                      <div className="empty-row">
                        Keine Konten passen zu Suche und Filter.
                      </div>
                    ) : null}
                  </div>
                </div>
              )}
              <p className="muted small no-margin">
                Löschlinks stammen ausschließlich aus dem JustDeleteMe-Datensatz
                (jdm-contrib/jdm). Fehlt ein Eintrag, zeigt Quitly keinen Link
                an. Den Status setzt du selbst, sobald die Löschung bestätigt
                ist.
              </p>
            </section>
          )}
        </>
      )}

      {detail ? (
        <ServiceDetail
          mailboxId={mailboxF}
          service={detail}
          onClose={() => setDetailId(null)}
          onStatus={(sv, st) => void changeStatus(sv, st)}
        />
      ) : null}
      {linksOpen ? (
        <OpenLinksDialog
          services={selectedServices}
          onClose={() => setLinksOpen(false)}
        />
      ) : null}
    </div>
  );
}
