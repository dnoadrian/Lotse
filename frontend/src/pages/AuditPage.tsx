// „Protokoll“: Audit-Log der eigenen Aktionen.
import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { AuditEntry } from "../api/types";
import { Banner, PageHeader, Spinner, useIsPhone } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { auditActionLabel, auditDetailSummary, isAuditWarning } from "../lib/mappings";

const LIMITS = [100, 250, 500];

export function AuditPage() {
  const isPhone = useIsPhone();
  const [limit, setLimit] = useState(100);
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [accountNames, setAccountNames] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (n: number) => {
    setLoading(true);
    try {
      setEntries(await ep.getAudit(n));
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(limit);
  }, [limit, load]);

  useEffect(() => {
    ep.getAccounts()
      .then((list) => setAccountNames(Object.fromEntries(list.map((a) => [a.id, a.label]))))
      .catch(() => undefined);
  }, []);

  return (
    <div className="page">
      <PageHeader
        title="Protokoll"
        intro="Anmeldungen, Änderungen und Löschvorgänge. Passwörter, Tokens, Betreffzeilen und Mail-Inhalte werden nie protokolliert."
        actions={
          <>
            <label className="field-compact">
              Einträge
              <select className="select" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                {LIMITS.map((n) => (
                  <option key={n} value={n}>
                    Letzte {n}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn btn-secondary" onClick={() => void load(limit)} disabled={loading}>
              Aktualisieren
            </button>
          </>
        }
      />
      {error ? (
        <Banner kind="error" onClose={() => setError(null)}>
          {error}
        </Banner>
      ) : null}
      {!entries ? (
        error ? null : <Spinner />
      ) : entries.length === 0 ? (
        <div className="empty-card">
          <p className="muted no-margin">Noch keine Einträge.</p>
        </div>
      ) : isPhone ? (
        <ul className="audit-cards">
          {entries.map((e) => (
            <li key={e.id} className="audit-card">
              <div className="audit-card-head">
                <span className={`strong${isAuditWarning(e.action) ? " text-red" : ""}`}>{auditActionLabel(e.action)}</span>
                <span className="mono small muted">{formatDateTime(e.ts)}</span>
              </div>
              {auditDetailSummary(e.detail, accountNames) ? (
                <span className="small break">{auditDetailSummary(e.detail, accountNames)}</span>
              ) : null}
              <span className="mono small muted">{e.ip || "—"}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="table-box">
          <table className="audit-table">
            <thead>
              <tr>
                <th scope="col">Zeit</th>
                <th scope="col">Aktion</th>
                <th scope="col">Details</th>
                <th scope="col">IP</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="mono small nowrap">{formatDateTime(e.ts)}</td>
                  <td className={isAuditWarning(e.action) ? "text-red strong" : "strong"}>{auditActionLabel(e.action)}</td>
                  <td className="muted break">{auditDetailSummary(e.detail, accountNames) || "—"}</td>
                  <td className="mono small muted nowrap">{e.ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
