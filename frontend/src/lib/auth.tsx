import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setCsrfToken, setUnauthorizedHandler } from "../api/client";
import * as ep from "../api/endpoints";
import type { SessionUser } from "../api/types";

export type AuthStatus = "loading" | "anonymous" | "authenticated" | "unreachable";

interface AuthCtx {
  status: AuthStatus;
  mfaPending: boolean;
  user: SessionUser | null;
  /** Sitzung vom Server neu laden (setzt CSRF-Token und Benutzer). */
  refresh: () => Promise<void>;
  /** Nach erfolgreicher Anmeldung aufrufen. */
  completeLogin: (csrfToken: string) => Promise<void>;
  logout: () => Promise<void>;
  setTotpEnabled: (enabled: boolean) => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [mfaPending, setMfaPending] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);

  const becomeAnonymous = useCallback((pending = false) => {
    setCsrfToken(null);
    setUser(null);
    setMfaPending(pending);
    setStatus("anonymous");
  }, []);

  const refresh = useCallback(async () => {
    try {
      const s = await ep.getSession();
      if (s.authenticated && s.csrf_token) {
        setCsrfToken(s.csrf_token);
        setUser(s.user ?? null);
        setMfaPending(false);
        setStatus("authenticated");
      } else {
        becomeAnonymous(!!s.mfa_pending);
      }
    } catch {
      setCsrfToken(null);
      setStatus("unreachable");
    }
  }, [becomeAnonymous]);

  useEffect(() => {
    setUnauthorizedHandler(() => becomeAnonymous(false));
    void refresh();
    return () => setUnauthorizedHandler(() => {});
  }, [refresh, becomeAnonymous]);

  const completeLogin = useCallback(
    async (csrfToken: string) => {
      setCsrfToken(csrfToken);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    try {
      await ep.logout();
    } catch {
      // auch bei Fehler lokal abmelden
    }
    becomeAnonymous(false);
  }, [becomeAnonymous]);

  const setTotpEnabled = useCallback((enabled: boolean) => {
    setUser((u) => (u ? { ...u, totp_enabled: enabled } : u));
  }, []);

  const value = useMemo(
    () => ({ status, mfaPending, user, refresh, completeLogin, logout, setTotpEnabled }),
    [status, mfaPending, user, refresh, completeLogin, logout, setTotpEnabled],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth außerhalb von AuthProvider");
  return v;
}
