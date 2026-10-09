import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Schriften lokal aus npm (keine externen Anfragen)
import "@fontsource/geist-sans/latin-400.css";
import "@fontsource/geist-sans/latin-500.css";
import "@fontsource/geist-sans/latin-600.css";
import "@fontsource/geist-sans/latin-700.css";
import "@fontsource/geist-mono/latin-400.css";
import "@fontsource/geist-mono/latin-500.css";
import "./styles/app.css";
import { App } from "./App";
import { applyTheme, readStoredTheme } from "./lib/theme";

// Design vor dem ersten Rendern setzen (ohne Inline-Skript wegen CSP)
applyTheme(readStoredTheme());

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
