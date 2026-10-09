// Fortschritt eines Scans mit den vier Schritten (Connect.dc.html).
import type { Account, Job } from "../api/types";
import { formatNumber } from "../lib/format";
import { SCAN_STEPS, isActive, stepState } from "../lib/scans";
import { ProgressBar } from "./ui";

function statusText(job: Job): string {
  switch (job.status) {
    case "queued":
      return "In der Warteschlange";
    case "running":
      return "Läuft";
    case "done":
      return "Abgeschlossen";
    case "cancelled":
      return "Abgebrochen";
    case "error":
      return "Fehlgeschlagen";
    default:
      return job.status;
  }
}

export function ScanJobProgress({ job, account, onCancel }: { job: Job; account?: Account; onCancel?: () => void }) {
  const active = isActive(job);
  const name = account ? account.label : `Postfach #${job.account_id}`;
  const progress = job.status === "done" ? 1 : job.progress;
  return (
    <div className="scan-job">
      <div className="scan-job-head">
        <div className="scan-job-title">
          <span className="strong">{name}</span>
          <span className={`muted scan-job-status scan-status-${job.status}`}>{statusText(job)}</span>
        </div>
        <div className="scan-job-meta muted mono">
          {job.messages_total > 0
            ? `${formatNumber(job.messages_seen)} / ${formatNumber(job.messages_total)} Mails`
            : `${formatNumber(job.messages_seen)} Mails`}
          {" · "}
          {formatNumber(job.signals_found)} Signale
        </div>
        {active && onCancel ? (
          <button type="button" className="btn btn-danger-text btn-sm" onClick={onCancel}>
            Abbrechen
          </button>
        ) : null}
      </div>
      <ProgressBar value={progress} label={`Scan-Fortschritt ${name}`} className={`progress-${job.status}`} />
      <ol className="scan-steps">
        {SCAN_STEPS.map((s, i) => {
          const st = stepState(job, i);
          return (
            <li key={s.key} className={`scan-step step-${st === "läuft" ? "running" : st === "fertig" ? "done" : st === "fehler" ? "error" : "idle"}`}>
              <span className="scan-step-dot" aria-hidden="true">
                {st === "fertig" ? "✓" : st === "fehler" ? "!" : String(i + 1)}
              </span>
              <div className="scan-step-text">
                <span className="strong">{s.label}</span>
                <span className="muted small">{st}</span>
              </div>
            </li>
          );
        })}
      </ol>
      {job.status === "error" && job.error ? <p className="text-red small no-margin">{job.error}</p> : null}
    </div>
  );
}

export function ScanProgressList({
  jobs,
  accounts,
  onCancel,
  onlyActive = false,
}: {
  jobs: Record<number, Job>;
  accounts: Account[];
  onCancel?: (jobId: number) => void;
  onlyActive?: boolean;
}) {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const list = Object.values(jobs)
    .filter((j) => byId.has(j.account_id))
    .filter((j) => !onlyActive || isActive(j))
    .sort((a, b) => a.account_id - b.account_id);
  if (list.length === 0) return null;
  return (
    <div className="scan-list" aria-live="polite">
      {list.map((j) => (
        <ScanJobProgress key={j.id} job={j} account={byId.get(j.account_id)} onCancel={onCancel ? () => onCancel(j.id) : undefined} />
      ))}
    </div>
  );
}
