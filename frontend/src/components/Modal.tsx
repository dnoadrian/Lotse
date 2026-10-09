// Dialog mit Fokusfalle, Esc zum Schließen und Fokus-Rückgabe.
import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true" && el.offsetParent !== null,
  );
}

interface ModalProps {
  onClose: () => void;
  labelledBy: string;
  describedBy?: string;
  children: ReactNode;
  /** "dialog" = zentriert, "drawer" = Seitenleiste rechts */
  variant?: "dialog" | "drawer";
  initialFocus?: RefObject<HTMLElement | null>;
  /** Schließen per Esc/Klick außerhalb sperren (z. B. während einer Anfrage) */
  busy?: boolean;
  className?: string;
}

export function Modal({ onClose, labelledBy, describedBy, children, variant = "dialog", initialFocus, busy, className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    document.body.classList.add("modal-open");
    const target = initialFocus?.current ?? (panel ? focusables(panel)[0] : null) ?? panel;
    target?.focus();

    function onKey(e: KeyboardEvent) {
      if (!panel) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        if (!busyRef.current) onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables(panel);
      if (items.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panel.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.classList.remove("modal-open");
      if (previous && typeof previous.focus === "function" && document.contains(previous)) previous.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return createPortal(
    <div
      className={`overlay overlay-${variant}`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busyRef.current) onCloseRef.current();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={`${variant === "drawer" ? "drawer" : "dialog"}${className ? " " + className : ""}`}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
