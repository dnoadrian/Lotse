// Schlanker Fetch-Client für die Quitly-API.
// - Ändernde Anfragen tragen immer X-Quitly-Request: 1 und Content-Type: application/json
// - Nach dem Login zusätzlich X-CSRF-Token (nur im Speicher gehalten, nie in localStorage)
// - 401 → Callback (Weiterleitung zur Anmeldung)

export const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export function isUnsafeMethod(method: string): boolean {
  return UNSAFE_METHODS.has(method.toUpperCase());
}

/** Baut die Header für eine Anfrage. Reine Funktion – leicht testbar. */
export function buildHeaders(method: string, csrfToken: string | null | undefined): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (isUnsafeMethod(method)) {
    headers["X-Quitly-Request"] = "1";
    headers["Content-Type"] = "application/json";
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }
  return headers;
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: "Die Anfrage war ungültig.",
  401: "Bitte melde dich an.",
  403: "Sicherheitsprüfung fehlgeschlagen. Bitte lade die Seite neu.",
  404: "Nicht gefunden.",
  409: "Die Daten haben sich geändert. Bitte neu laden.",
  413: "Die Anfrage ist zu groß.",
  415: "Ungültiges Datenformat.",
  422: "Ungültige Eingabe.",
  429: "Zu viele Anfragen. Bitte kurz warten.",
  500: "Interner Fehler. Bitte später erneut versuchen.",
  502: "Der Mailserver hat nicht wie erwartet geantwortet.",
  503: "Der Dienst ist gerade nicht erreichbar.",
};

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfter: number | null;
  readonly fields: string[];

  constructor(status: number, detail: string, retryAfter: number | null = null, fields: string[] = []) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
    this.fields = fields;
  }
}

/** Retry-After (Sekunden oder HTTP-Datum) in Sekunden umrechnen. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return parseInt(trimmed, 10);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

/** Fehlermeldung aus einem Fehler-Body ableiten: bevorzugt `detail` (deutsche Server-Meldung). */
export function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string" && d.trim()) return d;
  }
  return FALLBACK_MESSAGES[status] ?? `Unerwarteter Fehler (${status}).`;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error && err.message) return err.message;
  return "Unbekannter Fehler.";
}

export interface RequestOptions {
  /** 401 nicht global behandeln (z. B. auf der Anmeldeseite). */
  noAuthRedirect?: boolean;
  signal?: AbortSignal;
}

export interface ApiClientConfig {
  getCsrfToken: () => string | null;
  onUnauthorized: () => void;
  fetchImpl?: typeof fetch;
}

export interface ApiClient {
  request<T>(method: HttpMethod, path: string, body?: unknown, opts?: RequestOptions): Promise<T>;
  get<T>(path: string, opts?: RequestOptions): Promise<T>;
  post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T>;
  put<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T>;
  patch<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T>;
  del<T>(path: string, opts?: RequestOptions): Promise<T>;
}

export function createApiClient(config: ApiClientConfig): ApiClient {
  const doFetch = config.fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));

  async function request<T>(method: HttpMethod, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
    if (!path.startsWith("/api/")) throw new Error("Ungültiger API-Pfad");
    const init: RequestInit = {
      method,
      headers: buildHeaders(method, config.getCsrfToken()),
      credentials: "same-origin",
      cache: "no-store",
      signal: opts.signal,
    };
    if (body !== undefined) init.body = JSON.stringify(body);

    let res: Response;
    try {
      res = await doFetch(path, init);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError(0, "Server nicht erreichbar. Bitte Verbindung prüfen.");
    }

    let data: unknown = null;
    const ctype = res.headers.get("content-type") ?? "";
    if (ctype.includes("application/json")) {
      try {
        data = await res.json();
      } catch {
        data = null;
      }
    }

    if (!res.ok) {
      if (res.status === 401 && !opts.noAuthRedirect) config.onUnauthorized();
      const fields =
        data && typeof data === "object" && Array.isArray((data as { fields?: unknown }).fields)
          ? ((data as { fields: unknown[] }).fields.filter((f) => typeof f === "string") as string[])
          : [];
      throw new ApiError(res.status, errorMessage(res.status, data), parseRetryAfter(res.headers.get("retry-after")), fields);
    }
    return data as T;
  }

  return {
    request,
    get: (p, o) => request("GET", p, undefined, o),
    post: (p, b, o) => request("POST", p, b, o),
    put: (p, b, o) => request("PUT", p, b, o),
    patch: (p, b, o) => request("PATCH", p, b, o),
    del: (p, o) => request("DELETE", p, undefined, o),
  };
}

// ---------------------------------------------------------------- App-weite Instanz

let csrfToken: string | null = null;
let unauthorizedHandler: () => void = () => {};

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler;
}

export const api = createApiClient({
  getCsrfToken: () => csrfToken,
  onUnauthorized: () => unauthorizedHandler(),
});
