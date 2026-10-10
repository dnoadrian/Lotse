// Detailansicht eines Dienstes als Seitenleiste – inkl. erkannter Mails und Erklärung der Prozent.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Service, ServiceMails, ServiceStatus } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { ServiceIcon } from "../components/ServiceIcon";
import { CopyButton, Spinner } from "../components/ui";
import { formatDate, formatDateTime, formatNumber } from "../lib/format";
import {
  confidencePercent,
  deletionBadge,
  difficultyMeta,
  providerLabel,
  qualityMeta,
} from "../lib/mappings";
import { buildMailto, isSafeHttpUrl } from "../lib/url";
import { StatusSelect } from "./StatusSelect";

export function ServiceDetail({
  service,
  onClose,
  onStatus,
}: {
  service: Service;
  onClose: () => void;
  onStatus: (s: Service, status: ServiceStatus) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const [mails, setMails] = useState<ServiceMails | null>(null);
  const [mailsError, setMailsError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setMails(null);
    setMailsError(null);
    ep.getServiceMails(service.id, ctrl.signal)
      .then((m) => {
        if (!ctrl.signal.aborted) setMails(m);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setMailsError(errorText(err));
      });
    return () => ctrl.abort();
  }, [service.id]);

  function openMail(accountId: number, folder: string, uid: string) {
    const params = new URLSearchParams({
      konto: String(accountId),
      ordner: folder,
      mail: uid,
    });
    navigate(`/emails?${params.toString()}`);
  }

  const jdm = service.jdm;
  const diff = difficultyMeta(jdm?.difficulty);
  const q = qualityMeta(service.quality);
  const pct = confidencePercent(service.confidence);
  const mailto = jdm
    ? buildMailto(jdm.email, jdm.email_subject, jdm.email_body)
    : null;
  const titleId = `svc-title-${service.id}`;
  const emailText = jdm
    ? [
        jdm.email ? `An: ${jdm.email}` : "",
        jdm.email_subject ? `Betreff: ${jdm.email_subject}` : "",
        jdm.email_body ?? "",
      ]
        .filter(Boolean)
        .join("\n\n")
    : "";

  return (
    <Modal
      onClose={onClose}
      labelledBy={titleId}
      variant="drawer"
      initialFocus={closeRef}
    >
      <div className="drawer-head">
        <ServiceIcon id={service.id} name={service.name} large />
        <div className="drawer-title">
          <h2 id={titleId}>{service.name}</h2>
          <span className="muted mono small truncate">
            {service.domains.join(", ") || "—"}
          </span>
        </div>
        <button
          ref={closeRef}
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Details schließen"
        >
          <Icon name="close" />
        </button>
      </div>

      <div className="drawer-body">
        <div className="drawer-row">
          <StatusSelect service={service} onChange={onStatus} />
          {service.deletion_detected ? (
            <span className="badge badge-green">{deletionBadge(service)}</span>
          ) : null}
        </div>
        {service.lifecycle === "likely_deleted" ? (
          <div className="hint-card hint-inline">
            <p className="no-margin">
              Seit 14 Tagen keine Mail mehr nach deiner Löschanfrage. Wurde das
              Konto gelöscht?
            </p>
            <div className="hint-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => onStatus(service, "geloescht")}
              >
                Ja, gelöscht
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => onStatus(service, "offen")}
              >
                Noch aktiv
              </button>
            </div>
          </div>
        ) : null}
        {service.lifecycle === "still_active" ? (
          <p className="muted no-margin">
            Nach deiner Löschanfrage kamen weiter Konto-Mails – das Konto
            scheint noch aktiv.
          </p>
        ) : null}
        {service.lifecycle === "waiting" ? (
          <p className="muted no-margin">
            Löschung angefragt – Quitly prüft bei jedem Scan, ob noch Mails
            kommen.
          </p>
        ) : null}

        <section
          className="drawer-section"
          aria-labelledby={`${titleId}-mails`}
        >
          <h3 id={`${titleId}-mails`}>Erkannte Mails</h3>
          {mailsError ? (
            <p className="text-red no-margin">{mailsError}</p>
          ) : null}
          {!mails && !mailsError ? <Spinner /> : null}
          {mails ? (
            <>
              {mails.warnings.map((w) => (
                <p key={w} className="muted small no-margin">
                  {w}
                </p>
              ))}
              {mails.items.length === 0 ? (
                <p className="muted no-margin">
                  Die Mails sind nicht mehr im Postfach. Quitly erinnert sich
                  trotzdem an dieses Konto.
                </p>
              ) : (
                <ul className="found-mails">
                  {mails.items.map((m) => (
                    <li key={m.id}>
                      <button
                        type="button"
                        className="found-mail"
                        disabled={!m.still_in_mailbox}
                        onClick={() =>
                          openMail(m.account_id, m.folder, m.msg_ref)
                        }
                        aria-label={`${m.subject || m.label} öffnen`}
                      >
                        <span className="found-mail-top">
                          <span className="tag">{m.label}</span>
                          <span className="mono muted small">
                            {formatDateTime(m.received_at)}
                          </span>
                        </span>
                        <span
                          className={`found-mail-subject${m.seen === false ? " strong" : ""}`}
                        >
                          {m.still_in_mailbox
                            ? m.subject || "(kein Betreff)"
                            : "Nicht mehr im Postfach"}
                        </span>
                        <span className="muted small truncate">
                          {m.account_label} · {m.folder_name || m.folder}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : null}
        </section>

        <section className="drawer-section" aria-labelledby={`${titleId}-jdm`}>
          <h3 id={`${titleId}-jdm`}>Löschung</h3>
          {jdm ? (
            <>
              <dl className="kv">
                <dt>JDM-Eintrag</dt>
                <dd>{jdm.name}</dd>
                <dt>Aufwand</dt>
                <dd className={`tone-${diff.tone}`}>{diff.label}</dd>
              </dl>
              {isSafeHttpUrl(jdm.url) ? (
                <a
                  className="btn btn-secondary btn-link-blue"
                  href={jdm.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Löschseite öffnen
                  <Icon name="external" size={14} strokeWidth={2} />
                </a>
              ) : (
                <p className="muted no-margin">
                  Kein Löschlink im JustDeleteMe-Eintrag.
                </p>
              )}
              {jdm.instructions ? (
                <div className="stack-6">
                  <span className="strong">Anleitung</span>
                  <p className="prewrap no-margin">{jdm.instructions}</p>
                </div>
              ) : null}
              {jdm.email ? (
                <div className="mail-template">
                  <span className="strong">Löschung per E-Mail</span>
                  <dl className="kv">
                    <dt>Adresse</dt>
                    <dd className="mono break">{jdm.email}</dd>
                    {jdm.email_subject ? (
                      <>
                        <dt>Betreff</dt>
                        <dd className="break">{jdm.email_subject}</dd>
                      </>
                    ) : null}
                  </dl>
                  {jdm.email_body ? (
                    <pre className="mail-body">{jdm.email_body}</pre>
                  ) : null}
                  <div className="row-wrap">
                    <CopyButton text={emailText} label="Text kopieren" />
                    {mailto ? (
                      <a className="btn btn-secondary btn-sm" href={mailto}>
                        <Icon name="mail" size={16} /> Im Mailprogramm öffnen
                      </a>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted no-margin">
              Kein JustDeleteMe-Eintrag. Quitly zeigt deshalb keinen Löschlink
              an – suche die Löschoption in den Kontoeinstellungen des Dienstes.
            </p>
          )}
        </section>

        <section className="drawer-section" aria-labelledby={`${titleId}-det`}>
          <h3 id={`${titleId}-det`}>Erkennung</h3>
          <div className="quality">
            <div className="quality-head">
              <span>{q.label}</span>
              <span className="mono muted">{pct} %</span>
            </div>
            <div className="bar">
              <div
                className={`bar-fill ${q.barClass}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
          <dl className="kv">
            <dt>Mails</dt>
            <dd>{formatNumber(service.message_count)}</dd>
            <dt>Absender</dt>
            <dd>{formatNumber(service.sender_count)}</dd>
            <dt>Erstmals gesehen</dt>
            <dd>{formatDate(service.first_seen)}</dd>
            <dt>Zuletzt gesehen</dt>
            <dd>{formatDate(service.last_seen)}</dd>
          </dl>
          <div className="explain">
            <span className="strong">So entstehen {pct} %</span>
            <ul className="signal-list">
              {(service.explanation ?? []).map((e) => (
                <li key={e.category}>
                  <span>
                    {e.label}
                    {e.count > 1 ? (
                      <span className="muted"> × {e.count}</span>
                    ) : null}
                  </span>
                  <span className="mono muted">
                    {Math.round(e.best * 100)} %
                  </span>
                </li>
              ))}
            </ul>
            <p className="muted small no-margin">
              Jede erkannte Mail ist ein Hinweis mit eigenem Gewicht. Quitly
              rechnet sie zusammen, ohne über 100 % zu kommen: 1 − (1 − a) · (1
              − b) · … Ab 85 % gilt die Erkennung als hoch, ab 60 % als mittel.
              Gelöschte Mails bleiben im Gedächtnis.
            </p>
          </div>
        </section>

        <section className="drawer-section" aria-labelledby={`${titleId}-dom`}>
          <h3 id={`${titleId}-dom`}>Domains</h3>
          <ul className="chip-list">
            {service.domains.map((d) => (
              <li key={d} className="mono small">
                {d}
              </li>
            ))}
          </ul>
        </section>

        <section className="drawer-section" aria-labelledby={`${titleId}-src`}>
          <h3 id={`${titleId}-src`}>Quellen</h3>
          <ul className="source-list">
            {service.sources.map((s) => (
              <li key={s.account_id}>
                <span className="strong">{s.label}</span>
                <span className="muted small">
                  {providerLabel(s.provider)} · {formatNumber(s.messages)} Mails
                  · {formatNumber(s.signals)} Signale
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Modal>
  );
}
