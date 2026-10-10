import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Schriften lokal aus npm (keine externen Anfragen)
import "@fontsource-variable/bricolage-grotesque/index.css";
import "@fontsource-variable/instrument-sans/index.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./styles/app.css";
import { App } from "./App";
import { applyTheme } from "./lib/theme";

// Dunkles Design vor dem ersten Rendern setzen (ohne Inline-Skript wegen CSP)
applyTheme();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
