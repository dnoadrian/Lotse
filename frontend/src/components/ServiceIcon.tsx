// Favicon des Dienstes (über Quitly geladen, nie direkt von der fremden Seite); sonst der Anfangsbuchstabe.
import { useState } from "react";
import { faviconUrl } from "../api/endpoints";
import { serviceInitial } from "../lib/mappings";

export function ServiceIcon({
  id,
  name,
  large = false,
}: {
  id: number;
  name: string;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  return (
    <span
      className={`avatar${large ? " avatar-lg" : ""}${loaded && !failed ? " avatar-icon" : ""}`}
      aria-hidden="true"
    >
      {failed ? null : (
        <img
          src={faviconUrl(id)}
          alt=""
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      {loaded && !failed ? null : (
        <span className="avatar-letter">{serviceInitial(name)}</span>
      )}
    </span>
  );
}
