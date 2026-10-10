import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

// Ablauf wie ein echter Benutzer – ausschließlich gegen das Dovecot-Testpostfach.
const USER = process.env.QUITLY_E2E_USER ?? "adrian";
const PASS = process.env.QUITLY_E2E_PASS ?? "demo-passwort-2026";
const SHOTS = new URL("../../docs/screenshots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

test.describe.configure({ mode: "serial" });

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Benutzername").fill(USER);
  await page.getByLabel("Passwort", { exact: true }).fill(PASS);
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page.getByRole("heading", { name: "Konten" })).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  // Testpostfach in definierten Zustand bringen
  execFileSync("python3", ["-I", new URL("../../scripts/test-imap/seed.py", import.meta.url).pathname], { stdio: "inherit" });
  // Testbenutzer anlegen (falls es ihn schon gibt, antwortet der Server mit 409)
  await request.post("/api/auth/register", {
    headers: { "X-Quitly-Request": "1" },
    data: { username: USER, password: PASS },
  });
});

test("Anmeldung: falsches Passwort wird abgewiesen", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.screenshot({ path: SHOTS + "desktop-login.png" });
  // Eigener Benutzername, damit die Brute-Force-Sperre den Testbenutzer nicht trifft
  await page.getByLabel("Benutzername").fill("gibt-es-nicht");
  await page.getByLabel("Passwort", { exact: true }).fill("falsches-passwort-123");
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page.getByRole("alert")).toContainText("Benutzername oder Passwort falsch");
});

test("Registrierung: eigenes Konto mit Auge, leeres Namensfeld, nur dunkles Design", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Konto erstellen" }).click();
  await expect(page.getByRole("heading", { name: "Konto erstellen" })).toBeVisible();
  const name = `e2e${Date.now() % 1_000_000}`;
  expect(await page.getByLabel("Benutzername").getAttribute("placeholder")).toBeFalsy();
  await expect(page.getByRole("button", { name: /Dunkles Design|Helles Design/ })).toHaveCount(0);
  await page.getByLabel("Benutzername").fill(name);
  const pw = page.getByLabel("Passwort", { exact: true });
  await pw.fill("abcd1");
  await expect(pw).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Passwort anzeigen" }).click();
  await expect(pw).toHaveAttribute("type", "text");
  await page.screenshot({ path: SHOTS + "desktop-registrierung-dunkel.png" });
  await page.getByRole("button", { name: "Konto erstellen" }).last().click();
  await expect(page.getByRole("heading", { name: "Konten" })).toBeVisible();
  // Neues Konto sieht keine fremden Daten
  await expect(page.getByText("GitHub")).toHaveCount(0);
});

test("Geschützte Seiten leiten ohne Anmeldung zur Anmeldung", async ({ page }) => {
  await page.goto("/emails");
  await expect(page).toHaveURL(/\/login/);
});

test("Postfach verbinden, scannen und Konten verwalten", async ({ page }) => {
  await login(page);
  const loaded = page.waitForResponse((r) => r.url().endsWith("/api/mail-accounts") && r.request().method() === "GET");
  await page.goto("/verbindungen");
  await expect(page.getByRole("heading", { name: "Verbindungen" })).toBeVisible();
  await loaded;

  // Formular erscheint erst, wenn die Postfach-Liste gerendert ist – erst dann zählen
  await expect(page.getByRole("heading", { name: "Postfach hinzufügen" })).toBeVisible();
  // Vorhandene Test-Postfächer entfernen, damit der Test wiederholbar ist
  const removeButtons = page.locator("section[aria-label='Verbundene Postfächer']").getByRole("button", { name: "Entfernen" });
  for (let n = await removeButtons.count(); n > 0; n--) {
    await removeButtons.first().click();
    await page.getByRole("dialog").getByRole("button", { name: /Entfernen/ }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(removeButtons).toHaveCount(n - 1);
  }

  const form = page.locator("section", { has: page.getByRole("heading", { name: "Postfach hinzufügen" }) });
  await form.getByLabel("Bezeichnung").fill("Testpostfach");
  await form.getByLabel("Server").fill("imap.quitly.test");
  await form.getByLabel("Port").fill("10993");
  await form.getByLabel("Benutzer").fill("test@quitly.test");
  await form.getByLabel("App-Passwort", { exact: true }).fill("test-passwort-123");
  const pw = form.getByLabel("App-Passwort", { exact: true });
  await expect(pw).toHaveAttribute("type", "password");
  await form.getByRole("button", { name: "Passwort anzeigen" }).click();
  await expect(pw).toHaveAttribute("type", "text");
  await form.getByRole("button", { name: "Verbinden & speichern" }).click();
  const card = page.locator("section[aria-label='Verbundene Postfächer']");
  await expect(card.getByRole("heading", { name: "Testpostfach" })).toHaveCount(1);

  await card.getByRole("button", { name: "Scan starten" }).first().click();
  await expect(page.getByText(/abgeschlossen/i).first()).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: SHOTS + "desktop-verbindungen.png", fullPage: true });

  await page.getByRole("link", { name: "Konten" }).first().click();
  await expect(page.getByRole("heading", { name: "Konten" })).toBeVisible();
  const table = page.getByRole("main");
  await expect(table.getByText("GitHub").first()).toBeVisible();
  await expect(table.getByText("Spotify").first()).toBeVisible();
  // Auch im Spam-Ordner gefunden; Löschanfrage und Adresswechsel erkannt
  await expect(table.getByText("Cloudflare").first()).toBeVisible();
  await expect(table.getByText("E-Mail geändert").first()).toBeVisible();
  // Nur sichere Konten: reiner Kontakt ohne Konto-Hinweis erscheint nicht
  await expect(table.getByText("Kulturverein")).toHaveCount(0);
  // Kein erfundener Link für Dienste ohne JustDeleteMe-Eintrag
  await expect(table.getByText("Kein JDM-Eintrag").first()).toBeVisible();
  // Link für GitHub stammt aus dem JDM-Datensatz
  const ghRow = page.locator("[data-service-name='GitHub'], tr, .svc-row, article", { hasText: "GitHub" }).first();
  const link = ghRow.getByRole("link", { name: /Löschseite/ });
  await expect(link).toHaveAttribute("href", /^https:\/\/github\.com\/settings\/admin/);
  await expect(link).toHaveAttribute("rel", /noopener/);
  await page.screenshot({ path: SHOTS + "desktop-konten.png", fullPage: true });

  // Mehrfachauswahl: mehrere Konten gleichzeitig markieren
  for (const n of ["GitHub", "Spotify", "Cloudflare"]) {
    await page.getByRole("checkbox", { name: `${n} auswählen` }).check();
  }
  await expect(page.getByText("3 ausgewählt")).toBeVisible();
  await page.screenshot({ path: SHOTS + "desktop-konten-auswahl.png" });
  await page.getByRole("button", { name: "Auswahl aufheben" }).click().catch(() => undefined);

  // Suche
  await page.getByRole("searchbox").first().fill("spoti");
  await expect(table.getByText("GitHub")).toHaveCount(0);
  await expect(table.getByText("Spotify").first()).toBeVisible();
  // Status manuell setzen und nach Neuladen prüfen
  const statusSelect = page.getByRole("combobox", { name: /Status.*Spotify/ }).first();
  await statusSelect.selectOption("angefragt");
  await page.waitForResponse((r) => r.url().includes("/api/services/") && r.request().method() === "PATCH");
  await page.reload();
  await page.getByRole("searchbox").first().fill("spoti");
  await expect(page.getByRole("combobox", { name: /Status.*Spotify/ }).first()).toHaveValue("angefragt");
});

test("Zwei Postfächer gleichzeitig, Konten nach Postfach filtern, Bereich mit Shift auswählen", async ({ page }) => {
  await login(page);
  await page.goto("/verbindungen");
  const card = page.locator("section[aria-label='Verbundene Postfächer']");
  await expect(card.getByRole("heading", { name: "Testpostfach", exact: true })).toHaveCount(1);
  const form = page.locator("section", { has: page.getByRole("heading", { name: "Postfach hinzufügen" }) });
  await form.getByLabel("Bezeichnung").fill("Zweitpostfach");
  await form.getByLabel("Server").fill("imap.quitly.test");
  await form.getByLabel("Port").fill("10993");
  await form.getByLabel("Benutzer").fill("zweit@quitly.test");
  await form.getByLabel("App-Passwort", { exact: true }).fill("zweit-passwort-123");
  await form.getByRole("button", { name: "Verbinden & speichern" }).click();
  await expect(card.getByRole("heading", { name: "Zweitpostfach" })).toHaveCount(1);
  await expect(card.getByRole("heading", { name: "Testpostfach", exact: true })).toHaveCount(1);
  const second = card.locator("article, .conn-card", { has: page.getByRole("heading", { name: "Zweitpostfach" }) }).first();
  await second.getByRole("button", { name: "Scan starten" }).click();
  const progress = page.locator("section[aria-labelledby='scan-h']");
  await expect(progress.getByText("Zweitpostfach")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("progressbar", { name: "Scan-Fortschritt Zweitpostfach" })).toBeVisible();
  await expect(progress.getByText(/4 \/ 4 Mails/)).toBeVisible({ timeout: 45_000 });

  await page.getByRole("link", { name: "Konten" }).first().click();
  const table = page.getByRole("main");
  await expect(table.getByText("Tebex").first()).toBeVisible();
  await page.getByLabel("Postfach").selectOption({ label: "Zweitpostfach (zweit@quitly.test)" });
  await expect(table.getByText("Tebex").first()).toBeVisible();
  await expect(table.getByText("Epic Games").first()).toBeVisible();
  await expect(table.getByText("GitHub").first()).toBeVisible(); // in beiden Postfächern
  await expect(table.getByText("Spotify")).toHaveCount(0);
  await page.screenshot({ path: SHOTS + "desktop-konten-postfach.png" });

  // Shift-Klick wählt den ganzen Bereich
  const boxes = page.getByRole("checkbox", { name: / auswählen$/ });
  const n = await boxes.count();
  expect(n).toBeGreaterThanOrEqual(4);
  await boxes.nth(0).check();
  await page.keyboard.down("Shift");
  await boxes.nth(3).check();
  await page.keyboard.up("Shift");
  await expect(page.getByText("4 ausgewählt")).toBeVisible();
  await page.getByLabel("Postfach").selectOption({ label: "Alle Postfächer" });
  await expect(table.getByText("Spotify").first()).toBeVisible();
});

test("E-Mails: Auswahl mit Bestätigung löschen und Ergebnis prüfen", async ({ page }) => {
  await login(page);
  await page.goto("/emails");
  await expect(page.getByRole("heading", { name: "E-Mails" })).toBeVisible();
  await expect(page.getByText("Welcome to GitHub, test!")).toBeVisible();
  await page.screenshot({ path: SHOTS + "desktop-emails.png", fullPage: true });

  // Zwei Nachrichten auswählen
  await page.getByRole("checkbox", { name: /Kulturverein: Programm im Oktober/ }).check();
  await page.getByRole("checkbox", { name: /Kulturverein: Programm im September/ }).check();
  await page.getByRole("button", { name: "Ausgewählte löschen" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const confirm = dialog.getByRole("button", { name: /Papierkorb|löschen/i }).last();
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill("LÖSCHEN");
  await page.screenshot({ path: SHOTS + "desktop-loeschdialog.png" });
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: /bestätigt|verschoben/ })).toBeVisible();
  await expect(page.getByText("Programm im Oktober")).toHaveCount(0);

  // Nur Registrierungs-Mails anzeigen
  await page.getByLabel("Nur Registrierungs-Mails").check();
  await expect(page.getByText("Fotos vom Wochenende")).toHaveCount(0);
  await expect(page.getByText("Welcome to GitHub, test!")).toBeVisible();
});

test("Konten: erkannte Mail anklicken öffnet sie unter E-Mails", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Details zu GitHub" }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Erkannte Mails" })).toBeVisible();
  await expect(drawer.getByText(/So entstehen \d+ %/)).toBeVisible();
  await page.waitForTimeout(700); // Einblend-Animation abwarten
  await page.screenshot({ path: SHOTS + "desktop-konto-details.png" });
  await drawer.getByRole("button", { name: /Welcome to GitHub, test! öffnen/ }).click();
  await expect(page).toHaveURL(/\/emails\?.*mail=/);
  const reader = page.getByRole("dialog");
  await expect(reader.getByRole("heading", { name: "Welcome to GitHub, test!" })).toBeVisible();
  await expect(reader.getByText("Erfundene Testnachricht.")).toBeVisible();
});

test("E-Mails: HTML-Mail sicher lesen, suchen, als ungelesen markieren", async ({ page }) => {
  await login(page);
  await page.goto("/emails");
  await page.getByRole("button", { name: /Willkommen bei Netflix/ }).first().click();
  const reader = page.getByRole("dialog");
  await expect(reader.getByRole("heading", { name: "Willkommen bei Netflix" })).toBeVisible();
  const frame = reader.locator("iframe");
  await expect(frame).toHaveAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox");
  await expect(frame.contentFrame().getByRole("heading", { name: "Willkommen bei Netflix" })).toBeVisible();
  await expect(reader.getByText("Externe Bilder sind blockiert")).toBeVisible();
  await expect(reader.getByRole("link", { name: /Abmelden/ })).toHaveAttribute("href", "https://www.netflix.com/unsubscribe");
  await page.waitForTimeout(700);
  await page.screenshot({ path: SHOTS + "desktop-mail-lesen.png" });
  await reader.getByRole("tab", { name: "Nur Text" }).click();
  await expect(reader.getByText("Dein Konto ist jetzt aktiv.")).toBeVisible();
  await reader.getByRole("button", { name: "Als ungelesen markieren" }).click();
  await expect(reader.getByRole("button", { name: "Als gelesen markieren" })).toBeVisible();
  await reader.getByRole("button", { name: "Nachricht schließen" }).click();

  // Suche auf dem Server, auch im Text
  await page.getByRole("searchbox").fill("Dropbox");
  await expect(page.getByRole("button", { name: /Dein Dropbox-Konto wurde gelöscht/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Welcome to GitHub/ })).toHaveCount(0);
});

test.describe("Mobil", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });

  test("Mobilansicht ohne horizontales Scrollen", async ({ page }) => {
    await login(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: SHOTS + "mobil-konten.png" });
    await page.goto("/emails");
    await expect(page.getByRole("heading", { name: "E-Mails" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    await page.screenshot({ path: SHOTS + "mobil-emails.png" });
    await page.goto("/login");
  });
});
