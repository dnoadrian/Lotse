import { Navigate, Route, Routes, useLocation, BrowserRouter } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LogoMark } from "./components/Logo";
import { AuthProvider, useAuth } from "./lib/auth";
import { ScanProvider } from "./lib/scans";
import { ThemeProvider } from "./lib/theme";
import { AuditPage } from "./pages/AuditPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { EmailsPage } from "./pages/EmailsPage";
import { LoginPage } from "./pages/LoginPage";
import { SecurityPage } from "./pages/SecurityPage";
import { ServicesPage } from "./pages/ServicesPage";

function Splash() {
  return (
    <div className="splash" role="status">
      <LogoMark size={48} />
      <span className="sr-only">Wird geladen …</span>
    </div>
  );
}

/** Nur angemeldet: sonst zur Anmeldung, mit Rücksprungziel. */
function Protected() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Splash />;
  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return (
    <ScanProvider>
      <Layout />
    </ScanProvider>
  );
}

function LoginRoute() {
  const { status } = useAuth();
  if (status === "loading") return <Splash />;
  return <LoginPage />;
}

function NotFound() {
  return (
    <div className="page">
      <h1>Seite nicht gefunden</h1>
      <p className="muted">Diese Adresse gibt es in Lotse nicht.</p>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginRoute />} />
            <Route element={<Protected />}>
              <Route index element={<ServicesPage />} />
              <Route path="emails" element={<EmailsPage />} />
              <Route path="verbindungen" element={<ConnectionsPage />} />
              <Route path="sicherheit" element={<SecurityPage />} />
              <Route path="protokoll" element={<AuditPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
