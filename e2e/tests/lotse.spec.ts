import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

// Ablauf wie ein echter Benutzer – ausschließlich gegen das Dovecot-Testpostfach.
const USER = process.env.LOTSE_E2E_USER ?? "adrian";
const PASS = process.env.LOTSE_E2E_PASS ?? "demo-passwort-2026";
const SHOTS = new URL("../../docs/screenshots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

test.describe.configure({ mode: "serial" });

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Benutzername").fill(USER);
  await page.getByLabel("Passwort").fill(PASS);
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page.getByRole("heading", { name: "Konten" })).toBeVisible();
}

async function setTheme(page: Page, theme: "light" | "dark") {
  const current = await page.evaluate(() => document.documentElement.dataset.theme);
  if (current !== theme) {
    await page.getByRole("button", { name: /Dunkles Design|Helles Design/ }).first().click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  }
}

test.beforeAll(() => {
  // Testpostfach in definierten Zustand bringen
  execFileSync("python3", ["-I", new URL("../../scripts/test-imap/seed.py", import.meta.url).pathname], { stdio: "inherit" });
});

test("Anmeldung: falsches Passwort wird abgewiesen", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.screenshot({ path: SHOTS + "desktop-login.png" });
  // Eigener Benutzername, damit die Brute-Force-Sperre den Testbenutzer nicht trifft
  await page.getByLabel("Benutzername").fill("gibt-es-nicht");
  await page.getByLabel("Passwort").fill("falsches-passwort-123");
  await page.getByRole("button", { name: "Weiter" }).click();
  await expect(page.getByRole("alert")).toContainText("Benutzername oder Passwort falsch");
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

  // Vorhandene Test-Postfächer entfernen, damit der Test wiederholbar ist
  const removeButtons = page.locator("section[aria-label='Verbundene Postfächer']").getByRole("button", { name: "Entfernen" });
  for (let n = await removeButtons.count(); n > 0; n--) {
    await removeButtons.first().click();
    await page.getByRole("dialog").getByRole("button", { name: /Entfernen/ }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(removeButtons).toHaveCount(n - 1);
  }

  const form = page.locator("section", { has: page.getByRole("heading", { name: "Mailcow / IMAP hinzufügen" }) });
  await form.getByLabel("Bezeichnung").fill("Mailcow Test");
  await form.getByLabel("Server").fill("imap.lotse.test");
  await form.getByLabel("Port").fill("10993");
  await form.getByLabel("Benutzer").fill("test@lotse.test");
  await form.getByLabel("App-Passwort").fill("test-passwort-123");
  await form.getByRole("button", { name: "Verbinden & speichern" }).click();
  const card = page.locator("section[aria-label='Verbundene Postfächer']");
  await expect(card.getByRole("heading", { name: "Mailcow Test" })).toHaveCount(1);

  await card.getByRole("button", { name: "Scan starten" }).first().click();
  await expect(page.getByText(/abgeschlossen/i).first()).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: SHOTS + "desktop-verbindungen.png", fullPage: true });

  await page.getByRole("link", { name: "Konten" }).first().click();
  await expect(page.getByRole("heading", { name: "Konten" })).toBeVisible();
  const table = page.getByRole("main");
  await expect(table.getByText("GitHub").first()).toBeVisible();
  await expect(table.getByText("Spotify").first()).toBeVisible();
  // Kein erfundener Link für Dienste ohne JustDeleteMe-Eintrag
  await expect(table.getByText("Kein JDM-Eintrag").first()).toBeVisible();
  // Link für GitHub stammt aus dem JDM-Datensatz
  const ghRow = page.locator("[data-service-name='GitHub'], tr, .svc-row, article", { hasText: "GitHub" }).first();
  const link = ghRow.getByRole("link", { name: /Löschseite/ });
  await expect(link).toHaveAttribute("href", /^https:\/\/github\.com\/settings\/admin/);
  await expect(link).toHaveAttribute("rel", /noopener/);
  await setTheme(page, "light");
  await page.screenshot({ path: SHOTS + "desktop-konten-hell.png", fullPage: true });
  await setTheme(page, "dark");
  await page.screenshot({ path: SHOTS + "desktop-konten-dunkel.png", fullPage: true });
  await setTheme(page, "light");

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

test.describe("Mobil", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });

  test("Mobilansicht ohne horizontales Scrollen", async ({ page }) => {
    await login(page);
    await setTheme(page, "light");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: SHOTS + "mobil-konten-hell.png" });
    await setTheme(page, "dark");
    await page.screenshot({ path: SHOTS + "mobil-konten-dunkel.png" });
    await setTheme(page, "light");
    await page.goto("/emails");
    await expect(page.getByRole("heading", { name: "E-Mails" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    await page.screenshot({ path: SHOTS + "mobil-emails.png" });
    await page.goto("/login");
  });
});
