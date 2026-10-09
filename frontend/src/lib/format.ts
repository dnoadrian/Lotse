// Datums- und Zahlenformatierung (deutsch).

/** ISO-Zeitstempel parsen; ohne Zeitzonenangabe gilt UTC (SQLite liefert naive Werte). */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  let s = value.trim();
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(s)) {
    s = s.replace(" ", "T") + "Z";
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const numberFmt = new Intl.NumberFormat("de-DE");

export function formatDate(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateFmt.format(d) : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  return d ? dateTimeFmt.format(d) : "—";
}

export function formatNumber(n: number): string {
  return numberFmt.format(n);
}

/** Datum aus dem JDM-Datenstand: ISO → TT.MM.JJJJ, sonst unverändert. */
export function formatLooseDate(value: string | null | undefined): string {
  if (!value) return "unbekannt";
  const d = parseDate(value);
  return d ? dateFmt.format(d) : value;
}

/** „4:59“ aus Sekunden. */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function plural(n: number, one: string, many: string): string {
  return `${formatNumber(n)} ${n === 1 ? one : many}`;
}
