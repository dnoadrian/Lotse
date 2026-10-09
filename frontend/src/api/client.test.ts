import { describe, expect, it, vi } from "vitest";
import { ApiError, buildHeaders, createApiClient, errorMessage, parseRetryAfter } from "./client";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("buildHeaders", () => {
  it("setzt bei GET keine Änderungs-Header", () => {
    const h = buildHeaders("GET", "tok");
    expect(h["X-Lotse-Request"]).toBeUndefined();
    expect(h["X-CSRF-Token"]).toBeUndefined();
    expect(h["Content-Type"]).toBeUndefined();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE", "post"])("setzt bei %s X-Lotse-Request, JSON und CSRF", (m) => {
    const h = buildHeaders(m, "abc");
    expect(h["X-Lotse-Request"]).toBe("1");
    expect(h["Content-Type"]).toBe("application/json");
    expect(h["X-CSRF-Token"]).toBe("abc");
  });

  it("lässt X-CSRF-Token vor dem Login weg", () => {
    const h = buildHeaders("POST", null);
    expect(h["X-Lotse-Request"]).toBe("1");
    expect("X-CSRF-Token" in h).toBe(false);
  });
});

describe("parseRetryAfter / errorMessage", () => {
  it("liest Sekunden und HTTP-Datum", () => {
    expect(parseRetryAfter("299")).toBe(299);
    expect(parseRetryAfter(null)).toBeNull();
    const now = Date.parse("2026-10-09T10:00:00Z");
    expect(parseRetryAfter("Fri, 09 Oct 2026 10:01:00 GMT", now)).toBe(60);
    expect(parseRetryAfter("unsinn")).toBeNull();
  });

  it("bevorzugt die deutsche Server-Meldung", () => {
    expect(errorMessage(400, { detail: "Kein IMAP-Postfach." })).toBe("Kein IMAP-Postfach.");
    expect(errorMessage(422, { detail: [{ msg: "x" }] })).toBe("Ungültige Eingabe.");
    expect(errorMessage(502, null)).toMatch(/Mailserver/);
    expect(errorMessage(418, null)).toMatch(/418/);
  });
});

describe("createApiClient", () => {
  it("sendet Header, Cookie-Modus und JSON-Body", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(200, { ok: true }));
    const client = createApiClient({ getCsrfToken: () => "csrf-1", onUnauthorized: vi.fn(), fetchImpl });
    await client.post("/api/services/bulk-status", { ids: [1], status: "angefragt" });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/services/bulk-status");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ ids: [1], status: "angefragt" }));
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Lotse-Request"]).toBe("1");
    expect(headers["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("liest den CSRF-Token bei jeder Anfrage neu", async () => {
    let token: string | null = null;
    const fetchImpl = vi.fn(async () => jsonResponse(200, {}));
    const client = createApiClient({ getCsrfToken: () => token, onUnauthorized: vi.fn(), fetchImpl });
    await client.post("/api/auth/login", {});
    token = "neu";
    await client.del("/api/mail-accounts/1");
    const first = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    const second = (fetchImpl.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(first["X-CSRF-Token"]).toBeUndefined();
    expect(second["X-CSRF-Token"]).toBe("neu");
  });

  it("meldet 401 an den Handler – außer bei noAuthRedirect", async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = vi.fn(async () => jsonResponse(401, { detail: "Benutzername oder Passwort falsch." }));
    const client = createApiClient({ getCsrfToken: () => null, onUnauthorized, fetchImpl });
    await expect(client.get("/api/services")).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    await expect(client.post("/api/auth/login", {}, { noAuthRedirect: true })).rejects.toMatchObject({
      detail: "Benutzername oder Passwort falsch.",
    });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("liefert Retry-After bei 429 und 409-Meldungen", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(429, { detail: "Zu viele Versuche." }, { "retry-after": "120" }))
      .mockResolvedValueOnce(jsonResponse(409, { detail: "Der Ordner hat sich geändert." }));
    const client = createApiClient({ getCsrfToken: () => null, onUnauthorized: vi.fn(), fetchImpl });
    const e1 = await client.post("/api/auth/login", {}).catch((e: unknown) => e);
    expect(e1).toBeInstanceOf(ApiError);
    expect((e1 as ApiError).retryAfter).toBe(120);
    const e2 = await client.post("/api/mail/1/delete", {}).catch((e: unknown) => e);
    expect((e2 as ApiError).status).toBe(409);
    expect((e2 as ApiError).detail).toBe("Der Ordner hat sich geändert.");
  });

  it("meldet Netzwerkfehler als Status 0 und weist fremde Pfade ab", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const client = createApiClient({ getCsrfToken: () => null, onUnauthorized: vi.fn(), fetchImpl });
    await expect(client.get("/api/config")).rejects.toMatchObject({ status: 0 });
    await expect(client.get("https://evil.example/api/x")).rejects.toThrow();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
