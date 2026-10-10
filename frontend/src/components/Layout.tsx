// App-Rahmen: Seitenleiste (Desktop) bzw. Kopfzeile + Tab-Leiste (Telefon).
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Icon, type IconName } from "./Icons";
import { Logo } from "./Logo";

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Konten", icon: "konten", end: true },
  { to: "/emails", label: "E-Mails", icon: "mail" },
  { to: "/verbindungen", label: "Verbindungen", icon: "link" },
  { to: "/sicherheit", label: "Sicherheit", icon: "shield" },
  { to: "/protokoll", label: "Protokoll", icon: "list" },
];

function MoreMenu() {
  const [open, setOpen] = useState(false);
  const { logout, user } = useAuth();
  const location = useLocation();
  const ref = useRef<HTMLDivElement>(null);
  const active =
    location.pathname.startsWith("/sicherheit") ||
    location.pathname.startsWith("/protokoll");

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="tab-more" ref={ref}>
      {open ? (
        <div className="more-sheet" id="more-sheet">
          <NavLink to="/sicherheit" className="more-item">
            <Icon name="shield" /> Sicherheit
          </NavLink>
          <NavLink to="/protokoll" className="more-item">
            <Icon name="list" /> Protokoll
          </NavLink>
          <div className="more-user muted">
            Angemeldet als {user?.username ?? "—"}
          </div>
          <button
            type="button"
            className="more-item more-logout"
            onClick={() => void logout()}
          >
            <Icon name="logout" /> Abmelden
          </button>
        </div>
      ) : null}
      <button
        type="button"
        className={`tab${active ? " active" : ""}`}
        aria-expanded={open}
        aria-controls="more-sheet"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="more" size={22} strokeWidth={2.6} />
        Mehr
      </button>
    </div>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  // Nach Seitenwechsel den Fokus auf den Inhalt setzen (Screenreader)
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="app">
      <a href="#inhalt" className="skip-link">
        Zum Inhalt springen
      </a>
      <nav className="sidebar" aria-label="Hauptnavigation">
        <div className="sidebar-logo">
          <Logo size={28} />
        </div>
        <div className="nav-list">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className="nav-link">
              <Icon name={n.icon} className="nav-icon" />
              {n.label}
            </NavLink>
          ))}
        </div>
        <div className="sidebar-foot">
          <div className="user-box">
            <div className="user-box-label">Angemeldet als</div>
            <div className="user-box-name">{user?.username ?? "—"}</div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void logout()}
            >
              Abmelden
            </button>
          </div>
        </div>
      </nav>

      <header className="mobile-header">
        <Logo size={26} textClass="logo-text logo-text-sm" />
      </header>

      <main id="inhalt" className="main" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>

      <nav className="tabbar" aria-label="Hauptnavigation (mobil)">
        {NAV.slice(0, 3).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className="tab">
            <Icon name={n.icon} size={22} />
            {n.label}
          </NavLink>
        ))}
        <MoreMenu />
      </nav>
    </div>
  );
}
