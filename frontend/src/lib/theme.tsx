import type { ReactNode } from "react";

// Quitly hat nur noch das dunkle Design.
export function applyTheme(): void {
  document.documentElement.dataset.theme = "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
