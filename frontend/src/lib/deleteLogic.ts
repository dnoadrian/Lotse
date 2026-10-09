// Regeln für das Löschen von E-Mails – identisch zur Server-Prüfung (docs/API.md).
import type { DeleteMode, DeleteRequest, DeleteResult, Provider } from "../api/types";

export const CONFIRM_WORD = "LÖSCHEN";

/** Bestätigungswort nötig, sobald mehr als eine Nachricht, ein ganzer Ordner/Filter oder endgültig gelöscht wird. */
export function needsConfirmation(mode: DeleteMode, count: number, permanent: boolean): boolean {
  return mode !== "selected" || count > 1 || permanent;
}

/** Eingabe normalisieren wie der Server (NFC, trim, Großschreibung). */
export function normalizeConfirmation(word: string): string {
  return word.normalize("NFC").trim().toUpperCase();
}

export function isConfirmationValid(word: string): boolean {
  return normalizeConfirmation(word) === CONFIRM_WORD;
}

export function canConfirm(mode: DeleteMode, count: number, permanent: boolean, word: string): boolean {
  if (count <= 0) return false;
  return !needsConfirmation(mode, count, permanent) || isConfirmationValid(word);
}

/** Gmail kennt in Lotse nur „in den Papierkorb“. */
export function permanentAllowed(provider: Provider): boolean {
  return provider !== "gmail";
}

/** Bei IMAP im Papierkorb ist jede Löschung endgültig. */
export function forcedPermanent(provider: Provider, folderSpecial: string): boolean {
  return provider === "imap" && folderSpecial === "trash";
}

export interface DeletePlan {
  folder: string;
  mode: DeleteMode;
  ids: string[];
  /** Anzahl laut Liste (total bei all/registration, sonst Anzahl ids) */
  count: number;
  uidvalidity: string;
}

export function buildDeleteRequest(plan: DeletePlan, permanent: boolean, word: string): DeleteRequest {
  const body: DeleteRequest = {
    folder: plan.folder,
    mode: plan.mode,
    ids: plan.mode === "selected" ? plan.ids : [],
    permanent,
    confirmation: needsConfirmation(plan.mode, plan.count, permanent) ? normalizeConfirmation(word) : "",
  };
  if (plan.mode !== "selected") body.expected_count = plan.count;
  if (plan.uidvalidity) body.uidvalidity = plan.uidvalidity;
  return body;
}

export interface ResultSummary {
  ok: boolean;
  headline: string;
  notes: string[];
}

export function summarizeDeleteResult(r: DeleteResult): ResultSummary {
  const notes: string[] = [];
  const ok = r.failed === 0;
  let headline: string;
  if (ok) {
    headline = r.moved_to_trash ? `${r.deleted} in den Papierkorb verschoben` : `${r.deleted} gelöscht`;
    if (r.verified) headline += " · vom Server bestätigt";
  } else {
    headline = `${r.failed} von ${r.requested} konnten nicht gelöscht werden`;
    if (r.deleted > 0) notes.push(r.moved_to_trash ? `${r.deleted} in den Papierkorb verschoben.` : `${r.deleted} gelöscht.`);
  }
  if (!r.verified) notes.push("Der Server-Abgleich war nicht möglich – bitte den Ordner prüfen.");
  if (r.already_missing > 0) notes.push(`${r.already_missing} waren bereits nicht mehr vorhanden.`);
  if (r.remaining > 0) {
    notes.push(
      `Noch ${r.remaining} Nachrichten übrig: Gmail erlaubt höchstens 1000 pro Vorgang. Bitte den Vorgang erneut ausführen.`,
    );
  }
  return { ok, headline, notes };
}
