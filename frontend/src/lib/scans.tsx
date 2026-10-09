// Scan-Aufträge app-weit verfolgen: starten, alle 1,5 s abfragen, abbrechen.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Job, JobStep } from "../api/types";

export const POLL_MS = 1500;

export const SCAN_STEPS: { key: JobStep; label: string }[] = [
  { key: "fetch", label: "Nachrichten abrufen" },
  { key: "classify", label: "Klassifizieren" },
  { key: "merge", label: "Dienste zusammenführen" },
  { key: "jdm", label: "JustDeleteMe-Abgleich" },
];

export type StepState = "fertig" | "läuft" | "wartet" | "abgebrochen" | "fehler";

export function isActive(job: Pick<Job, "status"> | null | undefined): boolean {
  return !!job && (job.status === "queued" || job.status === "running");
}

/** Zustand eines Scan-Schritts aus dem Job ableiten. */
export function stepState(job: Pick<Job, "status" | "step">, index: number): StepState {
  if (job.status === "done") return "fertig";
  const current = job.step ? SCAN_STEPS.findIndex((s) => s.key === job.step) : -1;
  if (job.status === "queued") return "wartet";
  if (index < current) return "fertig";
  if (index === current) {
    if (job.status === "error") return "fehler";
    if (job.status === "cancelled") return "abgebrochen";
    return "läuft";
  }
  if (current < 0 && index === 0) {
    if (job.status === "running") return "läuft";
    if (job.status === "error") return "fehler";
    if (job.status === "cancelled") return "abgebrochen";
  }
  return "wartet";
}

interface ScanCtx {
  /** Letzter Job je Postfach-ID */
  jobs: Record<number, Job>;
  anyActive: boolean;
  /** Erhöht sich, sobald ein Scan fertig wird (für Neuladen von Daten). */
  finishedVersion: number;
  start: (accountIds: number[], sinceDays?: number) => Promise<string[]>;
  cancelAll: () => Promise<void>;
  cancel: (jobId: number) => Promise<void>;
  reload: () => Promise<void>;
  clear: (accountId: number) => void;
}

const Ctx = createContext<ScanCtx | null>(null);

export function ScanProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Record<number, Job>>({});
  const [finishedVersion, setFinishedVersion] = useState(0);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;

  const merge = useCallback((list: Job[]) => {
    const prev = jobsRef.current;
    const next = { ...prev };
    let finished = false;
    for (const j of list) {
      const before = prev[j.account_id];
      if (before && before.id === j.id && isActive(before) && !isActive(j)) finished = true;
      if (!before || before.id <= j.id) next[j.account_id] = j;
    }
    jobsRef.current = next;
    setJobs(next);
    if (finished) setFinishedVersion((v) => v + 1);
  }, []);

  const reload = useCallback(async () => {
    try {
      const list = await ep.getLatestScans();
      const next: Record<number, Job> = {};
      for (const j of list) next[j.account_id] = j;
      jobsRef.current = next;
      setJobs(next);
    } catch {
      // still – Anzeige bleibt beim letzten Stand
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const anyActive = useMemo(() => Object.values(jobs).some(isActive), [jobs]);

  useEffect(() => {
    if (!anyActive) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      const active = Object.values(jobsRef.current).filter(isActive);
      const results = await Promise.all(
        active.map((j) =>
          ep.getScan(j.id).catch((err: unknown) => {
            if (err instanceof ApiError && err.status === 404) {
              return { ...j, status: "error" as const, error: "Scan nicht gefunden." };
            }
            return null;
          }),
        ),
      );
      if (!stopped) merge(results.filter((r): r is Job => r !== null));
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [anyActive, merge]);

  const start = useCallback(
    async (accountIds: number[], sinceDays?: number) => {
      const errors: string[] = [];
      const started: Job[] = [];
      for (const id of accountIds) {
        try {
          started.push(await ep.startScan(id, sinceDays));
        } catch (err) {
          // 409: läuft bereits – wird über reload() übernommen
          if (!(err instanceof ApiError && err.status === 409)) errors.push(errorText(err));
        }
      }
      merge(started);
      if (started.length < accountIds.length) {
        try {
          merge(await ep.getLatestScans());
        } catch {
          /* ignorieren */
        }
      }
      return errors;
    },
    [merge],
  );

  const cancel = useCallback(
    async (jobId: number) => {
      const job = await ep.cancelScan(jobId);
      merge([job]);
    },
    [merge],
  );

  const cancelAll = useCallback(async () => {
    const active = Object.values(jobsRef.current).filter(isActive);
    await Promise.all(active.map((j) => cancel(j.id).catch(() => undefined)));
  }, [cancel]);

  const clear = useCallback((accountId: number) => {
    const next = { ...jobsRef.current };
    delete next[accountId];
    jobsRef.current = next;
    setJobs(next);
  }, []);

  const value = useMemo(
    () => ({ jobs, anyActive, finishedVersion, start, cancel, cancelAll, reload, clear }),
    [jobs, anyActive, finishedVersion, start, cancel, cancelAll, reload, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useScans(): ScanCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useScans außerhalb von ScanProvider");
  return v;
}
