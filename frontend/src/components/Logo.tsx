// Kompassnadel aus zwei Dreiecken (Brand.dc.html).

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false" className="logo-mark">
      <g transform="rotate(45 16 16)">
        <polygon points="16,2.5 21,15.4 11,15.4" className="logo-needle" />
        <polygon points="11,16.6 21,16.6 16,29.5" className="logo-tail" />
      </g>
    </svg>
  );
}

export function Logo({ size = 28, textClass = "logo-text" }: { size?: number; textClass?: string }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className={textClass}>Quitly</span>
    </span>
  );
}
