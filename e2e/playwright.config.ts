import { defineConfig, devices } from "@playwright/test";

// Ende-zu-Ende-Tests gegen den laufenden Docker-Compose-Stack (HTTPS über Caddy).
// Voraussetzungen siehe docs/TESTING.md. Nur gegen das Dovecot-TESTPOSTFACH ausführen.
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.LOTSE_E2E_URL ?? "https://localhost",
    // Caddy nutzt lokal eine eigene CA ("tls internal"); nur im Testbrowser ignorieren
    ignoreHTTPSErrors: true,
    locale: "de-AT",
    timezoneId: "Europe/Vienna",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
