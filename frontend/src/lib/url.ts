// URL-Prüfungen für Links aus Serverdaten (JustDeleteMe).

/** Nur http(s)-Links werden als Link dargestellt. */
export function isSafeHttpUrl(url: string | null | undefined): url is string {
  if (!url || typeof url !== "string") return false;
  const trimmed = url.trim();
  if (!/^https?:\/\//i.test(trimmed)) return false;
  try {
    const u = new URL(trimmed);
    return (u.protocol === "https:" || u.protocol === "http:") && !!u.hostname;
  } catch {
    return false;
  }
}

const EMAIL_RE =
  /^[A-Za-z0-9._+\-!$'*=^`{|}~]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

export function isPlainEmail(
  address: string | null | undefined,
): address is string {
  return !!address && address.length <= 254 && EMAIL_RE.test(address.trim());
}

/** mailto-Link mit kodiertem Betreff/Text; null bei ungültiger Adresse. */
export function buildMailto(
  address: string | null | undefined,
  subject?: string | null,
  body?: string | null,
): string | null {
  if (!isPlainEmail(address)) return null;
  const params: string[] = [];
  if (subject) params.push(`subject=${encodeURIComponent(subject)}`);
  if (body) params.push(`body=${encodeURIComponent(body)}`);
  return `mailto:${encodeURIComponent(address.trim()).replace(/%40/g, "@")}${params.length ? "?" + params.join("&") : ""}`;
}
