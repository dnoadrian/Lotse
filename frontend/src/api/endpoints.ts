import { api } from "./client";
import type {
  Account,
  AppConfig,
  AuditEntry,
  CsrfResponse,
  DeleteRequest,
  DeleteResult,
  Folder,
  Job,
  LoginResponse,
  MessageList,
  OkResponse,
  PasswordChangeResponse,
  SecurityOverview,
  Service,
  ServiceStatus,
  SessionInfo,
  TotpSetup,
} from "./types";

const enc = encodeURIComponent;

// Anmeldung
export const getSession = () => api.get<SessionInfo>("/api/auth/session", { noAuthRedirect: true });
export const login = (username: string, password: string) =>
  api.post<LoginResponse>("/api/auth/login", { username, password }, { noAuthRedirect: true });
export const submitTotp = (code: string) => api.post<CsrfResponse>("/api/auth/totp", { code }, { noAuthRedirect: true });
export const getSetupStatus = () => api.get<{ needed: boolean }>("/api/setup/status", { noAuthRedirect: true });
export const completeSetup = (token: string, username: string, password: string) =>
  api.post<OkResponse>("/api/setup", { token, username, password }, { noAuthRedirect: true });
export const logout = () => api.post<OkResponse>("/api/auth/logout", undefined, { noAuthRedirect: true });

// Sicherheit
export const getSecurityOverview = () => api.get<SecurityOverview>("/api/security/overview");
export const totpSetup = () => api.post<TotpSetup>("/api/security/totp/setup");
export const totpEnable = (code: string) => api.post<OkResponse>("/api/security/totp/enable", { code });
export const totpDisable = (password: string, code: string) =>
  api.post<OkResponse>("/api/security/totp/disable", { password, code });
export const changePassword = (current_password: string, new_password: string) =>
  api.post<PasswordChangeResponse>("/api/security/password", { current_password, new_password });
export const revokeSession = (id: number) => api.del<OkResponse>(`/api/security/sessions/${enc(String(id))}`);
export const getAudit = (limit = 100) => api.get<AuditEntry[]>(`/api/security/audit?limit=${enc(String(limit))}`);

// Konfiguration
export const getConfig = () => api.get<AppConfig>("/api/config");

// Postfächer
export const getAccounts = () => api.get<Account[]>("/api/mail-accounts");
export interface ImapInput {
  label: string;
  host: string;
  port: number;
  username: string;
  password: string;
}
export const addImapAccount = (body: ImapInput) => api.post<Account>("/api/mail-accounts/imap", body);
export const updateImapAccount = (id: number, body: Partial<ImapInput>) =>
  api.put<Account>(`/api/mail-accounts/${enc(String(id))}/imap`, body);
export const testAccount = (id: number) => api.post<Account>(`/api/mail-accounts/${enc(String(id))}/test`);
export const removeAccount = (id: number) => api.del<OkResponse>(`/api/mail-accounts/${enc(String(id))}`);
export const startGmail = (label: string) =>
  api.post<{ authorization_url: string }>("/api/mail-accounts/gmail/start", { label });

// Scans
export const startScan = (account_id: number, since_days?: number) =>
  api.post<Job>("/api/scans", since_days ? { account_id, since_days } : { account_id });
export const getLatestScans = () => api.get<Job[]>("/api/scans");
export const getScan = (id: number) => api.get<Job>(`/api/scans/${enc(String(id))}`);
export const cancelScan = (id: number) => api.post<Job>(`/api/scans/${enc(String(id))}/cancel`);

// Dienste
export const getServices = () => api.get<Service[]>("/api/services");
export const setServiceStatus = (id: number, status: ServiceStatus) =>
  api.patch<Service>(`/api/services/${enc(String(id))}`, { status });
export const bulkServiceStatus = (ids: number[], status: ServiceStatus) =>
  api.post<{ updated: number }>("/api/services/bulk-status", { ids, status });
export const EXPORT_CSV_URL = "/api/services/export.csv";

// E-Mails
export const getFolders = (accountId: number) => api.get<Folder[]>(`/api/mail/${enc(String(accountId))}/folders`);

export interface MessageQuery {
  folder: string;
  page?: number;
  page_size?: number;
  only_registration?: boolean;
  cursor?: string | null;
}

export function messagesPath(accountId: number, q: MessageQuery): string {
  const params = new URLSearchParams();
  params.set("folder", q.folder);
  params.set("page", String(q.page ?? 1));
  params.set("page_size", String(q.page_size ?? 50));
  params.set("only_registration", q.only_registration ? "true" : "false");
  params.set("cursor", q.cursor ?? "");
  return `/api/mail/${enc(String(accountId))}/messages?${params.toString()}`;
}

export const getMessages = (accountId: number, q: MessageQuery, signal?: AbortSignal) =>
  api.get<MessageList>(messagesPath(accountId, q), { signal });

export const deleteMessages = (accountId: number, body: DeleteRequest) =>
  api.post<DeleteResult>(`/api/mail/${enc(String(accountId))}/delete`, body);
