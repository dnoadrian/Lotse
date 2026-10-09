// Zuordnungen von API-Werten zu deutschen Bezeichnungen und Farbklassen.
import type { Account, Folder, Quality, Service, ServiceStatus, SignalKey } from "../api/types";

// ---------------------------------------------------------------- Status

export interface StatusMeta {
  value: ServiceStatus;
  label: string;
}

export const STATUS_ORDER: ServiceStatus[] = ["offen", "angefragt", "geloescht", "behalten"];

export const STATUS_META: Record<ServiceStatus, StatusMeta> = {
  offen: { value: "offen", label: "Offen" },
  angefragt: { value: "angefragt", label: "Angefragt" },
  geloescht: { value: "geloescht", label: "Gelöscht" },
  behalten: { value: "behalten", label: "Behalten" },
};

export function isServiceStatus(v: unknown): v is ServiceStatus {
  return typeof v === "string" && (STATUS_ORDER as string[]).includes(v);
}

export function statusLabel(status: string): string {
  return isServiceStatus(status) ? STATUS_META[status].label : status;
}

// ---------------------------------------------------------------- Aufwand (JDM)

export type Tone = "green" | "text" | "red" | "red-strong" | "muted";

export interface DifficultyMeta {
  label: string;
  tone: Tone;
}

const DIFFICULTY: Record<string, DifficultyMeta> = {
  easy: { label: "Einfach", tone: "green" },
  medium: { label: "Mittel", tone: "text" },
  hard: { label: "Schwer", tone: "red" },
  impossible: { label: "Unmöglich", tone: "red-strong" },
  limited: { label: "Eingeschränkt", tone: "muted" },
};

export function difficultyMeta(difficulty: string | null | undefined): DifficultyMeta {
  if (!difficulty) return { label: "—", tone: "muted" };
  return DIFFICULTY[difficulty] ?? { label: "Unbekannt", tone: "muted" };
}

// ---------------------------------------------------------------- Erkennungsqualität

export interface QualityMeta {
  label: string;
  /** CSS-Klasse für den Balken */
  barClass: string;
}

const QUALITY: Record<Quality, QualityMeta> = {
  hoch: { label: "Hoch", barClass: "q-hoch" },
  mittel: { label: "Mittel", barClass: "q-mittel" },
  niedrig: { label: "Niedrig", barClass: "q-niedrig" },
};

export function qualityMeta(q: string): QualityMeta {
  return QUALITY[q as Quality] ?? QUALITY.niedrig;
}

export function confidencePercent(confidence: number): number {
  if (!Number.isFinite(confidence)) return 0;
  return Math.max(0, Math.min(100, Math.round(confidence * 100)));
}

// ---------------------------------------------------------------- Signale / Kategorien

export const SIGNAL_ORDER: SignalKey[] = ["welcome", "verification", "registration", "deletion", "notice"];

const SIGNAL_LABELS: Record<SignalKey, string> = {
  welcome: "Willkommen",
  verification: "Bestätigung",
  registration: "Registrierung",
  deletion: "Löschung",
  notice: "Hinweis",
};

export function signalLabel(key: string): string {
  return SIGNAL_LABELS[key as SignalKey] ?? key;
}

/** „Willkommen, Bestätigung“ – nur vorhandene Signale in fester Reihenfolge. */
export function signalSummary(signals: Partial<Record<string, number>> | null | undefined): string {
  if (!signals) return "Keine Signale";
  const parts = SIGNAL_ORDER.filter((k) => (signals[k] ?? 0) > 0).map((k) => SIGNAL_LABELS[k]);
  return parts.length ? parts.join(", ") : "Keine Signale";
}

const CATEGORY_LABELS: Record<SignalKey, string> = {
  welcome: "Willkommen",
  verification: "Bestätigung",
  registration: "Registrierung",
  deletion: "Kontolöschung",
  notice: "Hinweis",
};

export function categoryLabel(category: string | null | undefined): string | null {
  if (!category) return null;
  return CATEGORY_LABELS[category as SignalKey] ?? null;
}

// ---------------------------------------------------------------- Ordner

const FOLDER_NAMES: Record<string, string> = {
  inbox: "Posteingang",
  sent: "Gesendet",
  archive: "Archiv",
  drafts: "Entwürfe",
  junk: "Spam",
  trash: "Papierkorb",
};

export function folderDisplayName(folder: Pick<Folder, "name" | "special">): string {
  return FOLDER_NAMES[folder.special] ?? folder.name;
}

// ---------------------------------------------------------------- Postfächer

export function providerLabel(provider: string): string {
  if (provider === "gmail") return "Gmail";
  if (provider === "imap") return "IMAP";
  return provider;
}

export function accountOptionLabel(a: Pick<Account, "provider" | "label" | "email_address">): string {
  const kind = a.provider === "gmail" ? "Gmail" : "Mailcow";
  const addr = a.email_address && a.email_address !== a.label ? ` (${a.email_address})` : "";
  return `${kind} · ${a.label}${addr}`;
}

// ---------------------------------------------------------------- Dienste

export function serviceInitial(name: string): string {
  const ch = Array.from(name.trim())[0];
  return ch ? ch.toUpperCase() : "?";
}

export function mergedSendersNote(senderCount: number): string {
  return senderCount > 1 ? ` · ${senderCount} Absender zusammengeführt` : "";
}

export type LinkFilter = "alle" | "mit" | "ohne";
export type QualityFilter = "alle" | Quality;
export type StatusFilter = "alle" | ServiceStatus;

export interface ServiceFilter {
  query: string;
  status: StatusFilter;
  quality: QualityFilter;
  link: LinkFilter;
}

export function hasDeletionLink(s: Pick<Service, "jdm">): boolean {
  return !!s.jdm && !!s.jdm.url;
}

export function filterServices(services: Service[], f: ServiceFilter): Service[] {
  const q = f.query.trim().toLowerCase();
  return services.filter((s) => {
    if (f.status !== "alle" && s.status !== f.status) return false;
    if (f.quality !== "alle" && s.quality !== f.quality) return false;
    if (f.link === "mit" && !hasDeletionLink(s)) return false;
    if (f.link === "ohne" && hasDeletionLink(s)) return false;
    if (!q) return true;
    if (s.name.toLowerCase().includes(q)) return true;
    return s.domains.some((d) => d.toLowerCase().includes(q));
  });
}

export function statusCounts(services: Service[]): Record<"alle" | ServiceStatus, number> {
  const counts = { alle: services.length, offen: 0, angefragt: 0, geloescht: 0, behalten: 0 };
  for (const s of services) if (isServiceStatus(s.status)) counts[s.status] += 1;
  return counts;
}

// ---------------------------------------------------------------- Protokoll

const AUDIT_ACTIONS: Record<string, string> = {
  login: "Anmeldung",
  login_failed: "Anmeldung fehlgeschlagen",
  totp_failed: "2FA-Code falsch",
  logout: "Abmeldung",
  totp_enabled: "2FA aktiviert",
  totp_disabled: "2FA deaktiviert",
  password_changed: "Passwort geändert",
  session_revoked: "Sitzung beendet",
  account_added: "Postfach hinzugefügt",
  account_updated: "Postfach geändert",
  account_removed: "Postfach entfernt",
  scan_started: "Scan gestartet",
  service_status: "Status geändert",
  service_status_bulk: "Status mehrerer Dienste geändert",
  mail_delete: "E-Mails gelöscht",
  mail_delete_failed: "Löschen fehlgeschlagen",
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTIONS[action] ?? action;
}

export function isAuditWarning(action: string): boolean {
  return action === "login_failed" || action === "totp_failed" || action === "mail_delete_failed";
}

const DELETE_MODE_LABELS: Record<string, string> = {
  selected: "Auswahl",
  all: "ganzer Ordner",
  registration: "Registrierungs-Mails",
};

function scalar(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "";
  }
}

/** Kurze, deutsche Zusammenfassung der Detail-Felder eines Protokolleintrags (nur Text). */
export function auditDetailSummary(
  detail: Record<string, unknown> | null | undefined,
  accountNames: Record<number, string> = {},
): string {
  if (!detail || typeof detail !== "object") return "";
  const parts: string[] = [];
  const d = { ...detail };
  const take = (k: string): unknown => {
    const v = d[k];
    delete d[k];
    return v;
  };

  const provider = take("provider");
  const accountId = take("account_id");
  if (accountId !== undefined) {
    const name = typeof accountId === "number" ? accountNames[accountId] : undefined;
    parts.push(name ? `Postfach „${name}“` : `Postfach #${scalar(accountId)}`);
  }
  if (provider !== undefined) parts.push(providerLabel(scalar(provider)));

  const mode = take("mode");
  if (mode !== undefined) parts.push(DELETE_MODE_LABELS[scalar(mode)] ?? scalar(mode));
  const permanent = take("permanent");
  if (permanent !== undefined) parts.push(permanent ? "endgültig" : "Papierkorb");

  const requested = take("requested");
  const deleted = take("deleted");
  if (deleted !== undefined) {
    parts.push(requested !== undefined ? `${scalar(deleted)} von ${scalar(requested)} gelöscht` : `${scalar(deleted)} gelöscht`);
  } else if (requested !== undefined) {
    parts.push(`${scalar(requested)} angefordert`);
  }
  const failed = take("failed");
  if (failed !== undefined && Number(failed) > 0) parts.push(`${scalar(failed)} fehlgeschlagen`);
  const verified = take("verified");
  if (verified !== undefined) parts.push(verified ? "überprüft" : "nicht überprüft");

  const status = take("status");
  if (status !== undefined) parts.push(`Status: ${statusLabel(scalar(status))}`);
  const count = take("count");
  if (count !== undefined) parts.push(`${scalar(count)} Dienste`);
  const serviceId = take("service_id");
  if (serviceId !== undefined) parts.push(`Dienst #${scalar(serviceId)}`);
  const mfa = take("mfa");
  if (mfa) parts.push("mit 2FA");
  const revoked = take("other_sessions_revoked");
  if (revoked !== undefined) parts.push(`${scalar(revoked)} andere Sitzungen beendet`);
  const reason = take("reason");
  if (reason !== undefined) parts.push(scalar(reason));

  for (const [k, v] of Object.entries(d)) parts.push(`${k}: ${scalar(v)}`);
  return parts.filter(Boolean).join(" · ");
}
