// Datentypen gemäß docs/API.md

export interface SessionUser {
  username: string;
  totp_enabled: boolean;
}

export interface SessionInfo {
  authenticated: boolean;
  mfa_pending: boolean;
  csrf_token?: string;
  user?: SessionUser;
}

export interface LoginResponse {
  mfa_required: boolean;
  csrf_token?: string;
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface OkResponse {
  ok: boolean;
}

export interface SecuritySession {
  id: number;
  created_at: string;
  last_seen: string;
  ip: string;
  user_agent: string;
  current: boolean;
}

export interface SecurityOverview {
  totp_enabled: boolean;
  sessions: SecuritySession[];
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg_base64: string;
}

export interface PasswordChangeResponse {
  ok: boolean;
  other_sessions_revoked: number;
}

export interface AuditEntry {
  id: number;
  ts: string;
  action: string;
  detail: Record<string, unknown> | null;
  ip: string;
}

export interface AppConfig {
  imap_allowed_ports: number[];
  jdm: { entries: number; commit?: string; date?: string; source?: string };
}

export type Provider = "imap";

export interface Account {
  id: number;
  provider: Provider;
  label: string;
  email_address: string;
  imap_host: string | null;
  imap_port: number | null;
  status: "ok" | "error";
  last_error: string | null;
  created_at: string;
  last_scan_at: string | null;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";
export type JobStep = "fetch" | "classify" | "merge" | "jdm";

export interface Job {
  id: number;
  account_id: number;
  status: JobStatus;
  step: JobStep | null;
  progress: number;
  messages_total: number;
  messages_seen: number;
  signals_found: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export type Difficulty = "easy" | "medium" | "hard" | "impossible" | "limited";
export type ServiceStatus = "offen" | "angefragt" | "geloescht" | "behalten";
export type Quality = "hoch" | "mittel" | "niedrig";
export type SignalKey = "welcome" | "verification" | "registration" | "deletion" | "notice";

export interface JdmInfo {
  name: string;
  url: string | null;
  difficulty: Difficulty | string | null;
  instructions: string | null;
  email: string | null;
  email_subject: string | null;
  email_body: string | null;
  domains: string[];
}

export interface ServiceSource {
  account_id: number;
  label: string;
  provider: Provider;
  messages: number;
  signals: number;
}

export interface Service {
  id: number;
  name: string;
  domains: string[];
  jdm: JdmInfo | null;
  sources: ServiceSource[];
  message_count: number;
  signal_count: number;
  sender_count: number;
  signals: Partial<Record<SignalKey, number>>;
  confidence: number;
  quality: Quality;
  first_seen: string | null;
  last_seen: string | null;
  deletion_detected: boolean;
  status: ServiceStatus;
  status_changed_at: string | null;
}

export type FolderSpecial = "inbox" | "sent" | "archive" | "drafts" | "junk" | "trash" | "all" | "";

export interface Folder {
  id: string;
  name: string;
  special: FolderSpecial;
  count: number;
}

export interface MessageItem {
  id: string;
  from_name: string;
  from_addr: string;
  subject: string;
  date: string | null;
  category: SignalKey | string | null;
}

export interface MessageList {
  items: MessageItem[];
  total: number;
  page: number;
  page_size: number;
  uidvalidity: string;
  next_cursor?: string | null;
}

export type DeleteMode = "selected" | "all" | "registration";

export interface DeleteRequest {
  folder: string;
  mode: DeleteMode;
  ids: string[];
  permanent: boolean;
  expected_count?: number;
  uidvalidity?: string;
  confirmation: string;
}

export interface DeleteResult {
  requested: number;
  deleted: number;
  already_missing: number;
  failed: number;
  failed_ids: string[];
  moved_to_trash: boolean;
  verified: boolean;
  remaining: number;
}
