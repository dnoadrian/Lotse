import { describe, expect, it } from "vitest";
import {
  buildDeleteRequest,
  canConfirm,
  forcedPermanent,
  isConfirmationValid,
  needsConfirmation,
  summarizeDeleteResult,
} from "./deleteLogic";

describe("needsConfirmation", () => {
  it("einzelne Nachricht in den Papierkorb braucht kein Wort", () => {
    expect(needsConfirmation("selected", 1, false)).toBe(false);
  });
  it("mehrere Nachrichten, ganzer Ordner, Registrierungs-Mails oder endgültig brauchen das Wort", () => {
    expect(needsConfirmation("selected", 2, false)).toBe(true);
    expect(needsConfirmation("selected", 1, true)).toBe(true);
    expect(needsConfirmation("all", 1, false)).toBe(true);
    expect(needsConfirmation("registration", 0, false)).toBe(true);
  });
});

describe("Bestätigungswort", () => {
  it("akzeptiert LÖSCHEN unabhängig von Groß-/Kleinschreibung und Leerzeichen", () => {
    expect(isConfirmationValid("LÖSCHEN")).toBe(true);
    expect(isConfirmationValid("  löschen ")).toBe(true);
    // zerlegtes Ö (NFD) wird normalisiert
    expect(isConfirmationValid("LÖSCHEN")).toBe(true);
  });
  it("lehnt Abweichungen ab", () => {
    expect(isConfirmationValid("LOESCHEN")).toBe(false);
    expect(isConfirmationValid("LÖSCHE")).toBe(false);
    expect(isConfirmationValid("")).toBe(false);
  });
  it("canConfirm verlangt das Wort nur wenn nötig", () => {
    expect(canConfirm("selected", 1, false, "")).toBe(true);
    expect(canConfirm("selected", 3, false, "")).toBe(false);
    expect(canConfirm("selected", 3, false, "löschen")).toBe(true);
    expect(canConfirm("all", 10, false, "nein")).toBe(false);
    expect(canConfirm("all", 0, false, "LÖSCHEN")).toBe(false);
  });
});

describe("Provider-Regeln", () => {
  it("IMAP-Papierkorb löscht immer endgültig", () => {
    expect(forcedPermanent("imap", "trash")).toBe(true);
    expect(forcedPermanent("imap", "inbox")).toBe(false);
  });
});

describe("buildDeleteRequest", () => {
  it("sendet bei Auswahl die IDs ohne expected_count", () => {
    const req = buildDeleteRequest(
      {
        folder: "INBOX",
        mode: "selected",
        ids: ["5"],
        count: 1,
        uidvalidity: "77",
      },
      false,
      "",
    );
    expect(req).toEqual({
      folder: "INBOX",
      mode: "selected",
      ids: ["5"],
      permanent: false,
      confirmation: "",
      uidvalidity: "77",
    });
  });
  it("sendet bei Ordner/Registrierung expected_count und das Wort", () => {
    const req = buildDeleteRequest(
      {
        folder: "INBOX",
        mode: "all",
        ids: ["1", "2"],
        count: 42,
        uidvalidity: "77",
      },
      true,
      " löschen",
    );
    expect(req.ids).toEqual([]);
    expect(req.expected_count).toBe(42);
    expect(req.confirmation).toBe("LÖSCHEN");
    expect(req.permanent).toBe(true);
    const reg = buildDeleteRequest(
      {
        folder: "INBOX",
        mode: "registration",
        ids: [],
        count: 7,
        uidvalidity: "",
      },
      false,
      "LÖSCHEN",
    );
    expect(reg.expected_count).toBe(7);
    expect("uidvalidity" in reg).toBe(false);
  });
});

describe("summarizeDeleteResult", () => {
  const base = {
    requested: 3,
    deleted: 3,
    already_missing: 0,
    failed: 0,
    failed_ids: [],
    moved_to_trash: true,
    verified: true,
    remaining: 0,
  };
  it("meldet Erfolg", () => {
    expect(summarizeDeleteResult(base)).toEqual({
      ok: true,
      headline: "3 in den Papierkorb verschoben · vom Server bestätigt",
      notes: [],
    });
    expect(
      summarizeDeleteResult({ ...base, moved_to_trash: false }).headline,
    ).toBe("3 gelöscht · vom Server bestätigt");
  });
  it("meldet Fehler, bereits fehlende und verbleibende Nachrichten", () => {
    const r = summarizeDeleteResult({
      ...base,
      deleted: 1,
      failed: 2,
      already_missing: 1,
      remaining: 500,
    });
    expect(r.ok).toBe(false);
    expect(r.headline).toBe("2 von 3 konnten nicht gelöscht werden");
    expect(r.notes.join(" ")).toMatch(/bereits nicht mehr vorhanden/);
    expect(r.notes.join(" ")).toMatch(/erneut ausführen/);
  });
});
