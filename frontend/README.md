# Lotse – Frontend

React 18, TypeScript, Vite, react-router. Keine UI-Bibliotheken; Design-Tokens als CSS-Variablen
(hell = Standard, dunkel per Umschalter). Schriften Geist/Geist Mono werden selbst ausgeliefert.

```bash
npm ci
npm run dev        # http://localhost:5173, /api wird an http://127.0.0.1:8000 weitergeleitet
npm run typecheck
npm test           # vitest
npm run build      # Ausgabe in dist/ (wird im Caddy-Image ausgeliefert)
```

Die App muss unter einer strikten CSP laufen (kein Inline-Script/-Style, keine externen Quellen).
API-Beschreibung: `../docs/API.md`.
