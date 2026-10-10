// Eine Mail lesen: Text sofort, Original-HTML nur in einem sandboxed iframe ohne Skripte.
// Externe Bilder bleiben blockiert, bis man sie ausdrücklich lädt (Schutz vor Tracking-Pixeln).
import { useEffect, useRef, useState } from "react";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Account, Folder, MessageDetail } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { Spinner } from "../components/ui";
import { formatDateTime, formatNumber } from "../lib/format";
import { categoryLabel, folderDisplayName } from "../lib/mappings";
import { isSafeHttpUrl } from "../lib/url";

const IMAGES_KEY = "quitly-images-always";

function readAlways(): boolean {
  try {
    return window.localStorage.getItem(IMAGES_KEY) === "1";
  } catch {
    return false;
  }
}

function writeAlways(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(IMAGES_KEY, "1");
    else window.localStorage.removeItem(IMAGES_KEY);
  } catch {
    /* Speicher nicht verfügbar – gilt dann nur für diese Ansicht */
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} B`;
  if (bytes < 1024 * 1024)
    return `${formatNumber(Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

export function MailReader({
  account,
  folder,
  uid,
  folders,
  onClose,
  onSeenChange,
  onMoved,
  onDelete,
}: {
  account: Account;
  folder: string;
  uid: string;
  folders: Folder[];
  onClose: () => void;
  onSeenChange: (uid: string, seen: boolean) => void;
  onMoved: (uid: string) => void;
  onDelete: (uid: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [mail, setMail] = useState<MessageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"text" | "html">("text");
  const [always, setAlways] = useState(readAlways);
  const [images, setImages] = useState(always);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [target, setTarget] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    setMail(null);
    setError(null);
    setImages(readAlways());
    setNotice(null);
    ep.getMessage(account.id, folder, uid, ctrl.signal)
      .then(async (m) => {
        if (ctrl.signal.aborted) return;
        setMail(m);
        setView(m.has_html ? "html" : "text");
        if (!m.seen) {
          // Öffnen markiert als gelesen – wie in jedem Mailprogramm
          try {
            await ep.setSeen(account.id, folder, [uid], true);
            setMail((cur) => (cur ? { ...cur, seen: true } : cur));
            onSeenChange(uid, true);
          } catch {
            /* nicht kritisch */
          }
        }
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setError(errorText(err));
      });
    return () => ctrl.abort();
  }, [account.id, folder, uid]);

  async function toggleSeen() {
    if (!mail) return;
    setBusy(true);
    try {
      await ep.setSeen(account.id, folder, [uid], !mail.seen);
      setMail({ ...mail, seen: !mail.seen });
      onSeenChange(uid, !mail.seen);
    } catch (err) {
      setNotice(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function move() {
    if (!target) return;
    setBusy(true);
    try {
      const r = await ep.moveMessages(account.id, folder, [uid], target);
      if (r.moved === 1) {
        onMoved(uid);
        onClose();
      } else {
        setNotice("Die Nachricht konnte nicht verschoben werden.");
      }
    } catch (err) {
      setNotice(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const titleId = `mail-title-${uid}`;
  const cat = mail ? categoryLabel(mail.category) : null;
  const moveTargets = folders.filter((f) => f.id !== folder);

  return (
    <Modal
      onClose={onClose}
      labelledBy={titleId}
      variant="drawer"
      initialFocus={closeRef}
      className="reader-drawer"
    >
      <div className="drawer-head">
        <div className="drawer-title">
          <h2 id={titleId}>
            {mail ? mail.subject || "(kein Betreff)" : "Nachricht"}
          </h2>
          {mail ? (
            <span className="muted small truncate">{mail.from}</span>
          ) : null}
        </div>
        <button
          ref={closeRef}
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Nachricht schließen"
        >
          <Icon name="close" />
        </button>
      </div>

      <div className="drawer-body">
        {error ? <p className="text-red no-margin">{error}</p> : null}
        {!mail && !error ? <Spinner label="Nachricht wird geladen …" /> : null}
        {mail ? (
          <>
            <dl className="kv reader-meta">
              <dt>Von</dt>
              <dd className="break">{mail.from || "—"}</dd>
              <dt>An</dt>
              <dd className="break">{mail.to || "—"}</dd>
              {mail.cc ? (
                <>
                  <dt>Cc</dt>
                  <dd className="break">{mail.cc}</dd>
                </>
              ) : null}
              <dt>Datum</dt>
              <dd className="mono">{formatDateTime(mail.date)}</dd>
              <dt>Ordner</dt>
              <dd>
                {folderDisplayName({
                  name: mail.folder_name,
                  special: folders.find((f) => f.id === folder)?.special ?? "",
                })}
              </dd>
            </dl>
            {cat ? (
              <span className="badge badge-blue self-start">{cat}</span>
            ) : null}

            <div className="reader-actions">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void toggleSeen()}
                disabled={busy}
              >
                {mail.seen
                  ? "Als ungelesen markieren"
                  : "Als gelesen markieren"}
              </button>
              {moveTargets.length ? (
                <span className="reader-move">
                  <label className="sr-only" htmlFor={`${titleId}-move`}>
                    Zielordner
                  </label>
                  <select
                    id={`${titleId}-move`}
                    className="select"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  >
                    <option value="">Verschieben nach …</option>
                    {moveTargets.map((f) => (
                      <option key={f.id} value={f.id}>
                        {folderDisplayName(f)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!target || busy}
                    onClick={() => void move()}
                  >
                    Verschieben
                  </button>
                </span>
              ) : null}
              <button
                type="button"
                className="btn btn-danger-outline btn-sm"
                onClick={() => onDelete(uid)}
              >
                <Icon name="trash" size={16} /> Löschen
              </button>
              {isSafeHttpUrl(mail.unsubscribe.https) ? (
                <a
                  className="btn btn-ghost btn-sm"
                  href={mail.unsubscribe.https ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Abmelden <Icon name="external" size={14} strokeWidth={2} />
                </a>
              ) : mail.unsubscribe.mailto ? (
                <a
                  className="btn btn-ghost btn-sm"
                  href={mail.unsubscribe.mailto}
                >
                  Abmelden per Mail
                </a>
              ) : null}
            </div>
            {notice ? (
              <p className="text-red small no-margin">{notice}</p>
            ) : null}

            {mail.has_html ? (
              <div className="seg-tabs" role="tablist" aria-label="Darstellung">
                <button
                  type="button"
                  role="tab"
                  aria-selected={view === "html"}
                  onClick={() => setView("html")}
                >
                  Original
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={view === "text"}
                  onClick={() => setView("text")}
                >
                  Nur Text
                </button>
              </div>
            ) : null}

            {view === "html" && mail.has_html ? (
              <div className="reader-html">
                <div className="reader-images">
                  {!images ? (
                    <>
                      <span className="muted small">
                        Externe Bilder sind blockiert – Schutz vor Tracking.
                      </span>
                      <span className="reader-image-actions">
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => setImages(true)}
                        >
                          Bilder laden
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            writeAlways(true);
                            setAlways(true);
                            setImages(true);
                          }}
                        >
                          Immer erlauben
                        </button>
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="muted small">
                        {always
                          ? "Externe Bilder werden immer geladen."
                          : "Externe Bilder für diese Mail geladen."}
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          writeAlways(false);
                          setAlways(false);
                          setImages(false);
                        }}
                      >
                        {always ? "Wieder blockieren" : "Blockieren"}
                      </button>
                    </>
                  )}
                </div>
                <iframe
                  key={images ? "img" : "noimg"}
                  title="Inhalt der Nachricht"
                  sandbox="allow-popups allow-popups-to-escape-sandbox"
                  referrerPolicy="no-referrer"
                  src={ep.messageHtmlUrl(account.id, folder, uid, images)}
                />
              </div>
            ) : (
              <pre className="reader-text">
                {mail.text || "(Diese Nachricht enthält keinen Text.)"}
              </pre>
            )}
            {mail.truncated ? (
              <p className="muted small no-margin">
                Die Nachricht ist sehr groß und wird nur gekürzt angezeigt.
              </p>
            ) : null}

            {mail.attachments.length ? (
              <section className="drawer-section" aria-label="Anhänge">
                <h3>Anhänge</h3>
                <ul className="source-list">
                  {mail.attachments.map((a, i) => (
                    <li key={`${a.name}-${i}`}>
                      <span className="strong break">{a.name}</span>
                      <span className="muted small">
                        {a.content_type} · {formatSize(a.size)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="muted small no-margin">
                  Anhänge werden aus Sicherheitsgründen nicht geöffnet oder
                  heruntergeladen.
                </p>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </Modal>
  );
}
