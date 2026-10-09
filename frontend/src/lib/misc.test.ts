import { describe, expect, it } from "vitest";
import { formatCountdown, formatDate, parseDate } from "./format";
import { pageTokens, totalPages } from "./pagination";
import { stepState } from "./scans";
import { buildMailto, isSafeHttpUrl } from "./url";

describe("URL-Prüfungen", () => {
  it("zeigt nur http(s)-Links", () => {
    expect(isSafeHttpUrl("https://example.com/delete")).toBe(true);
    expect(isSafeHttpUrl("http://example.com")).toBe(true);
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("data:text/html,x")).toBe(false);
    expect(isSafeHttpUrl("//example.com")).toBe(false);
    expect(isSafeHttpUrl(null)).toBe(false);
  });

  it("baut mailto-Links kodiert", () => {
    expect(buildMailto("privacy@example.com", "Konto löschen", "Hallo & tschüss")).toBe(
      "mailto:privacy@example.com?subject=Konto%20l%C3%B6schen&body=Hallo%20%26%20tsch%C3%BCss",
    );
    expect(buildMailto("a@b.co")).toBe("mailto:a@b.co");
    expect(buildMailto("x@y.com?bcc=evil@z.com")).toBeNull();
    expect(buildMailto("kein-email")).toBeNull();
  });
});

describe("Datum", () => {
  it("behandelt Zeitstempel ohne Zone als UTC", () => {
    expect(parseDate("2026-10-09T12:00:00")?.toISOString()).toBe("2026-10-09T12:00:00.000Z");
    expect(parseDate("2026-10-09T12:00:00+02:00")?.toISOString()).toBe("2026-10-09T10:00:00.000Z");
    expect(parseDate("unsinn")).toBeNull();
    expect(formatDate(null)).toBe("—");
    expect(formatCountdown(299)).toBe("4:59");
  });
});

describe("Blättern", () => {
  it("berechnet Seiten", () => {
    expect(totalPages(0, 50)).toBe(1);
    expect(totalPages(101, 50)).toBe(3);
    expect(pageTokens(1, 3)).toEqual([1, 2, 3]);
    expect(pageTokens(5, 20)).toEqual([1, "gap", 4, 5, 6, "gap", 20]);
    expect(pageTokens(1, 20)).toEqual([1, 2, "gap", 20]);
  });
});

describe("Scan-Schritte", () => {
  it("leitet den Zustand der Schritte ab", () => {
    expect(stepState({ status: "running", step: "classify" }, 0)).toBe("fertig");
    expect(stepState({ status: "running", step: "classify" }, 1)).toBe("läuft");
    expect(stepState({ status: "running", step: "classify" }, 2)).toBe("wartet");
    expect(stepState({ status: "done", step: "jdm" }, 3)).toBe("fertig");
    expect(stepState({ status: "queued", step: null }, 0)).toBe("wartet");
    expect(stepState({ status: "error", step: "fetch" }, 0)).toBe("fehler");
  });
});
