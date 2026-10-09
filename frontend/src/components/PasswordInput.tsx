// Passwortfeld mit Auge zum Ein-/Ausblenden (statt doppelter Eingabe).
import { useState, type InputHTMLAttributes } from "react";
import { Icon } from "./Icons";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function PasswordInput({ className, ...rest }: Props) {
  const [visible, setVisible] = useState(false);
  const label = visible ? "Passwort verbergen" : "Passwort anzeigen";
  return (
    <span className="password-wrap">
      <input {...rest} className={`${className ?? "input"} password-input`} type={visible ? "text" : "password"} />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-label={label}
        aria-pressed={visible}
        title={label}
      >
        <Icon name={visible ? "eyeOff" : "eye"} size={18} />
      </button>
    </span>
  );
}
