import { describe, expect, it } from "vitest";
import type { Service } from "../api/types";
import {
  auditActionLabel,
  auditDetailSummary,
  categoryLabel,
  confidencePercent,
  difficultyMeta,
  filterServices,
  folderDisplayName,
  mergedSendersNote,
  qualityMeta,
  signalSummary,
  statusCounts,
  statusLabel,
} from "./mappings";

function svc(over: Partial<Service>): Service {
  return {
    id: 1,
    name: "GitHub",
    domains: ["github.com"],
    jdm: null,
    sources: [],
    message_count: 1,
    signal_count: 1,
    sender_count: 1,
    signals: {},
    confidence: 0.9,
    quality: "hoch",
    first_seen: null,
    last_seen: null,
    deletion_detected: false,
    status: "offen",
    status_changed_at: null,
    ...over,
  };
}

const jdm = (url: string | null, difficulty = "easy") => ({
  name: "X",
  url,
  difficulty,
  instructions: null,
  email: null,
  email_subject: null,
  email_body: null,
  domains: [],
});

describe("Status und Aufwand", () => {
  it("übersetzt Status", () => {
    expect(statusLabel("offen")).toBe("Offen");
    expect(statusLabel("geloescht")).toBe("Gelöscht");
    expect(statusLabel("angefragt")).toBe("Angefragt");
    expect(statusLabel("behalten")).toBe("Behalten");
  });

  it("ordnet JDM-Schwierigkeit zu", () => {
    expect(difficultyMeta("easy")).toEqual({ label: "Einfach", tone: "green" });
    expect(difficultyMeta("medium")).toEqual({ label: "Mittel", tone: "text" });
    expect(difficultyMeta("hard")).toEqual({ label: "Schwer", tone: "red" });
    expect(difficultyMeta("impossible")).toEqual({
      label: "Unmöglich",
      tone: "red-strong",
    });
    expect(difficultyMeta("limited")).toEqual({
      label: "Eingeschränkt",
      tone: "muted",
    });
    expect(difficultyMeta(null).label).toBe("—");
    expect(difficultyMeta("seltsam").tone).toBe("muted");
  });

  it("ordnet Erkennungsqualität zu", () => {
    expect(qualityMeta("hoch").barClass).toBe("q-hoch");
    expect(qualityMeta("mittel").label).toBe("Mittel");
    expect(qualityMeta("niedrig").label).toBe("Niedrig");
    expect(confidencePercent(0.934)).toBe(93);
    expect(confidencePercent(1.7)).toBe(100);
    expect(confidencePercent(Number.NaN)).toBe(0);
  });
});

describe("Signale, Kategorien, Ordner", () => {
  it("fasst Signale in fester Reihenfolge zusammen", () => {
    expect(signalSummary({ verification: 2, welcome: 1 })).toBe(
      "Willkommen, Bestätigung",
    );
    expect(signalSummary({ deletion: 1, notice: 3, registration: 0 })).toBe(
      "Hinweis, Löschung",
    );
    expect(signalSummary({})).toBe("Keine Signale");
  });

  it("übersetzt Kategorien", () => {
    expect(categoryLabel("deletion")).toBe("Kontolöschung");
    expect(categoryLabel("registration")).toBe("Registrierung");
    expect(categoryLabel(null)).toBeNull();
    expect(categoryLabel("spam")).toBeNull();
  });

  it("benennt Spezialordner deutsch", () => {
    expect(folderDisplayName({ name: "INBOX", special: "inbox" })).toBe(
      "Posteingang",
    );
    expect(folderDisplayName({ name: "Junk", special: "junk" })).toBe("Spam");
    expect(folderDisplayName({ name: "Deleted Items", special: "trash" })).toBe(
      "Papierkorb",
    );
    expect(folderDisplayName({ name: "Rechnungen", special: "" })).toBe(
      "Rechnungen",
    );
  });

  it("zeigt zusammengeführte Absender nur ab zwei", () => {
    expect(mergedSendersNote(1)).toBe("");
    expect(mergedSendersNote(3)).toBe(" · 3 Absender zusammengeführt");
  });
});

describe("Filter", () => {
  const list = [
    svc({
      id: 1,
      name: "GitHub",
      domains: ["github.com"],
      jdm: jdm("https://github.com/settings/admin"),
    }),
    svc({
      id: 2,
      name: "Bäckerei Muster",
      domains: ["baeckerei-muster.at"],
      quality: "niedrig",
      status: "angefragt",
    }),
    svc({
      id: 3,
      name: "Spotify",
      domains: ["spotify.com"],
      jdm: jdm(null),
      quality: "mittel",
      status: "geloescht",
    }),
  ];
  const base = {
    query: "",
    status: "alle" as const,
    quality: "alle" as const,
    link: "alle" as const,
  };

  it("sucht in Name und Domain", () => {
    expect(
      filterServices(list, { ...base, query: "muster" }).map((s) => s.id),
    ).toEqual([2]);
    expect(
      filterServices(list, { ...base, query: "SPOTIFY.com" }).map((s) => s.id),
    ).toEqual([3]);
  });

  it("filtert nach Status, Qualität und Löschlink", () => {
    expect(
      filterServices(list, { ...base, status: "angefragt" }).map((s) => s.id),
    ).toEqual([2]);
    expect(
      filterServices(list, { ...base, quality: "mittel" }).map((s) => s.id),
    ).toEqual([3]);
    expect(
      filterServices(list, { ...base, link: "mit" }).map((s) => s.id),
    ).toEqual([1]);
    expect(
      filterServices(list, { ...base, link: "ohne" }).map((s) => s.id),
    ).toEqual([2, 3]);
  });

  it("zählt Status", () => {
    expect(statusCounts(list)).toEqual({
      alle: 3,
      offen: 1,
      angefragt: 1,
      geloescht: 1,
      behalten: 0,
    });
  });
});

describe("Protokoll", () => {
  it("übersetzt Aktionen", () => {
    expect(auditActionLabel("mail_delete")).toBe("E-Mails gelöscht");
    expect(auditActionLabel("login_failed")).toBe("Anmeldung fehlgeschlagen");
    expect(auditActionLabel("neu")).toBe("neu");
  });

  it("fasst Details zusammen", () => {
    expect(
      auditDetailSummary(
        {
          account_id: 2,
          provider: "imap",
          mode: "all",
          permanent: false,
          requested: 5,
          deleted: 5,
          failed: 0,
          verified: true,
        },
        { 2: "Mailcow" },
      ),
    ).toBe(
      "Postfach „Mailcow“ · IMAP · ganzer Ordner · Papierkorb · 5 von 5 gelöscht · überprüft",
    );
    expect(auditDetailSummary({ count: 3, status: "geloescht" })).toBe(
      "Status: Gelöscht · 3 Dienste",
    );
    expect(auditDetailSummary(null)).toBe("");
    expect(auditDetailSummary({ foo: "bar" })).toBe("foo: bar");
  });
});
