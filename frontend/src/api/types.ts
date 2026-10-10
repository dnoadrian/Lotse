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
export type SignalKey =
  | "welcome"
  | "verification"
  | "registration"
  | "deletion"
  | "deletion_request"
  | "email_change"
  | "email_new"
  | "security"
  | "subscription"
  | "order"
  | "account"
  | "notice"
  | "newsletter"
  | "contact";

export type Lifecycle = "still_active" | "likely_deleted" | "waiting";

export interface ExplanationItem {
  category: string;
  label: string;
  count: number;
  best: number;
  first: string | null;
  last: string | null;
}

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
  senders?: number;
  /** Nur dieses Postfach: Konto hier gelöscht bzw. Adresse von hier weg gewechselt */
  left?: "deleted" | "email_changed" | null;
  unconfirmed?: boolean;
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
  deletion_kind?: "deleted" | "email_changed" | null;
  deletion_requested_by_mail?: boolean;
  email_changed?: boolean;
  /** Nur eine Aufforderung zur Bestätigung kam, nie eine Konto-Mail danach */
  unconfirmed?: boolean;
  mails_in_mailbox?: number;
  memory_only?: boolean;
  lifecycle?: Lifecycle | null;
  explanation?: ExplanationItem[];
  status: ServiceStatus;
  status_changed_at: string | null;
}

export interface ServiceMail {
  id: number;
  account_id: number;
  account_label: string;
  folder: string;
  folder_name: string | null;
  msg_ref: string;
  category: string;
  label: string;
  score: number;
  reasons: string[];
  received_at: string | null;
  sender_domain: string;
  subject: string | null;
  from_name: string | null;
  from_addr: string | null;
  seen: boolean | null;
  still_in_mailbox: boolean;
}

export interface ServiceMails {
  items: ServiceMail[];
  explanation: ExplanationItem[];
  confidence: number;
  memory_only: boolean;
  warnings: string[];
}

export type FolderSpecial =
  | "inbox"
  | "sent"
  | "archive"
  | "drafts"
  | "junk"
  | "trash"
  | "all"
  | "";

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
  seen: boolean;
}

export interface MessageAttachment {
  name: string;
  content_type: string;
  size: number;
}

export interface MessageDetail {
  id: string;
  folder: string;
  folder_name: string;
  uidvalidity: string;
  seen: boolean;
  from: string;
  to: string;
  cc: string;
  date: string | null;
  subject: string;
  category: string | null;
  text: string;
  has_html: boolean;
  truncated: boolean;
  attachments: MessageAttachment[];
  unsubscribe: { https: string | null; mailto: string | null };
}

export interface MessageList {
  items: MessageItem[];
  total: number;
  page: number;
  page_size: number;
  uidvalidity: string;
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
