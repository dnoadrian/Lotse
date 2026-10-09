// Logo „Schnitt“: ein voller Kreis, von dem sich ein Segment löst – zusammen ein Q.

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false" className="logo-mark">
      <path d="M26 15A11 11 0 1 0 15 26Z" className="logo-body" />
      <path d="M29 18A11 11 0 0 1 18 29Z" className="logo-slice" />
    </svg>
  );
}

export function Logo({ size = 28, textClass = "logo-text" }: { size?: number; textClass?: string }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className={textClass}>quitly</span>
    </span>
  );
}
