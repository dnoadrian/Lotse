// Bestätigungsdialog für das Löschen von E-Mails (Mail.dc.html).
import { useId, useRef, useState, type FormEvent } from "react";
import { ApiError, errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { DeleteResult, Provider } from "../api/types";
import { Icon } from "../components/Icons";
import { Modal } from "../components/Modal";
import { ErrorBox } from "../components/ui";
import {
  CONFIRM_WORD,
  buildDeleteRequest,
  canConfirm,
  forcedPermanent,
  needsConfirmation,
  type DeletePlan,
} from "../lib/deleteLogic";

export interface DeleteDialogPlan extends DeletePlan {
  title: string;
  body: string;
}

export function DeleteDialog({
  plan,
  accountId,
  provider,
  folderSpecial,
  onCancel,
  onDone,
  onConflict,
}: {
  plan: DeleteDialogPlan;
  accountId: number;
  provider: Provider;
  folderSpecial: string;
  onCancel: () => void;
  onDone: (result: DeleteResult) => void;
  onConflict: (message: string) => void;
}) {
  const uid = useId();
  const titleId = `${uid}-title`;
  const descId = `${uid}-desc`;
  const forced = forcedPermanent(provider, folderSpecial);
  const [permanent, setPermanent] = useState(forced);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const needsWord = needsConfirmation(plan.mode, plan.count, permanent);
  const ok = canConfirm(plan.mode, plan.count, permanent, word);
  const isTrash = folderSpecial === "trash";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ok || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await ep.deleteMessages(
        accountId,
        buildDeleteRequest(plan, permanent, word),
      );
      onDone(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onConflict(err.detail);
        return;
      }
      setError(errorText(err));
      setBusy(false);
    }
  }

  const confirmLabel =
    (permanent ? "Endgültig löschen" : "In Papierkorb verschieben") +
    (plan.count > 1 ? ` (${plan.count})` : "");

  return (
    <Modal
      onClose={onCancel}
      labelledBy={titleId}
      describedBy={descId}
      busy={busy}
      initialFocus={cancelRef}
    >
      <form className="stack-18" onSubmit={submit}>
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-red" aria-hidden="true">
            <Icon name="alert" size={20} strokeWidth={2} />
          </span>
          <h2 id={titleId}>{plan.title}</h2>
        </div>
        <p id={descId} className="muted no-margin break">
          {plan.body}
        </p>

        <fieldset className="radio-group">
          <legend>Art der Löschung</legend>
          <label className={`radio${forced ? " is-disabled" : ""}`}>
            <input
              type="radio"
              name={`${uid}-mode`}
              checked={!permanent}
              disabled={forced}
              onChange={() => setPermanent(false)}
            />
            In den Papierkorb verschieben
          </label>
          <label className="radio">
            <input
              type="radio"
              name={`${uid}-mode`}
              checked={permanent}
              onChange={() => setPermanent(true)}
            />
            Endgültig löschen (nicht umkehrbar)
          </label>
          {isTrash ? (
            <p className="text-red small no-margin">
              Dieser Ordner ist der Papierkorb – Löschen ist hier immer
              endgültig.
            </p>
          ) : null}
        </fieldset>

        {needsWord ? (
          <label className="field">
            <span>
              Zur Bestätigung <strong className="mono">{CONFIRM_WORD}</strong>{" "}
              eingeben
            </span>
            <input
              className="input mono"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              value={word}
              onChange={(e) => setWord(e.target.value)}
              aria-invalid={word.length > 0 && !ok}
            />
          </label>
        ) : null}

        {error ? <ErrorBox>{error}</ErrorBox> : null}

        <div className="dialog-actions">
          <button
            ref={cancelRef}
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={busy}
          >
            Abbrechen
          </button>
          <button
            type="submit"
            className="btn btn-danger"
            disabled={!ok || busy}
          >
            {busy ? "Wird gelöscht …" : confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}
