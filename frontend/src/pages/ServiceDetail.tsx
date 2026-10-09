// Detailansicht eines Dienstes als Seitenleiste.
import { useRef } from "react";
import type { Service, ServiceStatus } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { CopyButton } from "../components/ui";
import { formatDate, formatNumber } from "../lib/format";
import {
  SIGNAL_ORDER,
  confidencePercent,
  difficultyMeta,
  providerLabel,
  qualityMeta,
  serviceInitial,
  signalLabel,
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
  const jdm = service.jdm;
  const diff = difficultyMeta(jdm?.difficulty);
  const q = qualityMeta(service.quality);
  const pct = confidencePercent(service.confidence);
  const mailto = jdm ? buildMailto(jdm.email, jdm.email_subject, jdm.email_body) : null;
  const titleId = `svc-title-${service.id}`;
  const emailText = jdm
    ? [jdm.email ? `An: ${jdm.email}` : "", jdm.email_subject ? `Betreff: ${jdm.email_subject}` : "", jdm.email_body ?? ""]
        .filter(Boolean)
        .join("\n\n")
    : "";

  return (
    <Modal onClose={onClose} labelledBy={titleId} variant="drawer" initialFocus={closeRef}>
      <div className="drawer-head">
        <span className="avatar avatar-lg" aria-hidden="true">
          {serviceInitial(service.name)}
        </span>
        <div className="drawer-title">
          <h2 id={titleId}>{service.name}</h2>
          <span className="muted mono small truncate">{service.domains.join(", ") || "—"}</span>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Details schließen">
          <Icon name="close" />
        </button>
      </div>

      <div className="drawer-body">
        <div className="drawer-row">
          <StatusSelect service={service} onChange={onStatus} />
          {service.deletion_detected ? <span className="badge badge-green">Löschung erkannt</span> : null}
        </div>

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
                <a className="btn btn-secondary btn-link-blue" href={jdm.url} target="_blank" rel="noopener noreferrer">
                  Löschseite öffnen
                  <Icon name="external" size={14} strokeWidth={2} />
                </a>
              ) : (
                <p className="muted no-margin">Kein Löschlink im JustDeleteMe-Eintrag.</p>
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
                  {jdm.email_body ? <pre className="mail-body">{jdm.email_body}</pre> : null}
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
              Kein JustDeleteMe-Eintrag. Quitly zeigt deshalb keinen Löschlink an – suche die Löschoption in den
              Kontoeinstellungen des Dienstes.
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
              <div className={`bar-fill ${q.barClass}`} style={{ width: `${pct}%` }} />
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
          <ul className="signal-list">
            {SIGNAL_ORDER.filter((k) => (service.signals[k] ?? 0) > 0).map((k) => (
              <li key={k}>
                <span>{signalLabel(k)}</span>
                <span className="mono muted">{service.signals[k]}</span>
              </li>
            ))}
          </ul>
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
                  {providerLabel(s.provider)} · {formatNumber(s.messages)} Mails · {formatNumber(s.signals)} Signale
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Modal>
  );
}
