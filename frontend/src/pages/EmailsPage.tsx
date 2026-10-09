// „E-Mails“: Ordner, Nachrichtenliste und Löschen (Mail.dc.html).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorText } from "../api/client";
import * as ep from "../api/endpoints";
import type { Account, DeleteResult, Folder, MessageItem, MessageList } from "../api/types";
import { Icon } from "../components/Icons";
import { Banner, PageHeader, Spinner, useIsPhone } from "../components/ui";
import { summarizeDeleteResult, type ResultSummary } from "../lib/deleteLogic";
import { formatDate, formatNumber } from "../lib/format";
import { accountOptionLabel, categoryLabel, folderDisplayName } from "../lib/mappings";
import { pageTokens, totalPages } from "../lib/pagination";
import { DeleteDialog, type DeleteDialogPlan } from "./DeleteDialog";

const PAGE_SIZE = 50;

function senderName(m: MessageItem): string {
  return m.from_name?.trim() || m.from_addr || "Unbekannter Absender";
}

export function EmailsPage() {
  const isPhone = useIsPhone();
  const [params, setParams] = useSearchParams();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [accountsError, setAccountsError] = useState<string | null>(null);

  const accountParam = Number(params.get("konto"));
  const account = useMemo(() => {
    if (!accounts?.length) return null;
    return accounts.find((a) => a.id === accountParam) ?? accounts[0];
  }, [accounts, accountParam]);

  // Ordner gehören immer zu genau einem Postfach – verhindert Abfragen mit fremder Ordner-ID beim Wechsel
  const [folderState, setFolderState] = useState<{ accountId: number; list: Folder[] } | null>(null);
  const folders = account && folderState?.accountId === account.id ? folderState.list : null;
  const [foldersError, setFoldersError] = useState<string | null>(null);
  const [folderId, setFolderId] = useState<string | null>(null);
  const [onlyReg, setOnlyReg] = useState(false);
  const [page, setPage] = useState(1);
  const [listing, setListing] = useState<MessageList | null>(null);
  const [items, setItems] = useState<MessageItem[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<DeleteDialogPlan | null>(null);
  const [result, setResult] = useState<ResultSummary | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const folder = folders?.find((f) => f.id === folderId) ?? null;
  const folderReady = folder !== null;
  const folderName = folder ? folderDisplayName(folder) : "";
  const cursorMode = account?.provider === "gmail" && !onlyReg;

  // Postfächer laden
  useEffect(() => {
    ep.getAccounts()
      .then((a) => {
        setAccounts(a);
        setAccountsError(null);
      })
      .catch((err) => setAccountsError(errorText(err)));
  }, []);

  // Ordner laden
  const loadFolders = useCallback(
    async (keepSelection: boolean) => {
      if (!account) return;
      setFoldersError(null);
      if (!keepSelection) setFolderState(null);
      try {
        const list = await ep.getFolders(account.id);
        setFolderState({ accountId: account.id, list });
        setFolderId((cur) => {
          if (keepSelection && cur && list.some((f) => f.id === cur)) return cur;
          return (list.find((f) => f.special === "inbox") ?? list[0])?.id ?? null;
        });
      } catch (err) {
        setFoldersError(errorText(err));
      }
    },
    [account],
  );

  useEffect(() => {
    setFolderId(null);
    setListing(null);
    setItems([]);
    void loadFolders(false);
  }, [loadFolders]);

  // Nachrichten laden (erste Seite bzw. Seite `page`)
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!account || !folderId || !folderReady) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setListLoading(true);
    setListError(null);
    ep.getMessages(
      account.id,
      { folder: folderId, page: cursorMode ? 1 : page, page_size: PAGE_SIZE, only_registration: onlyReg, cursor: null },
      ctrl.signal,
    )
      .then((res) => {
        if (ctrl.signal.aborted) return;
        setListing(res);
        setItems(res.items);
        setSelected(new Set());
        // Seite hinter dem Ende (z. B. nach dem Löschen) → letzte Seite
        if (!cursorMode && res.items.length === 0 && page > 1 && res.total > 0) {
          setPage(totalPages(res.total, res.page_size));
        }
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setListing(null);
        setItems([]);
        setListError(errorText(err));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setListLoading(false);
      });
    return () => ctrl.abort();
  }, [account, folderId, folderReady, onlyReg, page, cursorMode, reloadKey]);

  async function loadMore() {
    if (!account || !folderId || !listing?.next_cursor) return;
    setMoreLoading(true);
    try {
      const res = await ep.getMessages(account.id, {
        folder: folderId,
        page: 1,
        page_size: PAGE_SIZE,
        only_registration: onlyReg,
        cursor: listing.next_cursor,
      });
      setListing({ ...res, total: res.total || listing.total });
      setItems((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        return [...prev, ...res.items.filter((m) => !seen.has(m.id))];
      });
    } catch (err) {
      setListError(errorText(err));
    } finally {
      setMoreLoading(false);
    }
  }

  function reloadAll() {
    setPage((p) => (cursorMode ? 1 : p));
    setReloadKey((k) => k + 1);
    void loadFolders(true);
  }

  function chooseAccount(id: number) {
    const next = new URLSearchParams(params);
    next.set("konto", String(id));
    setParams(next, { replace: true });
    setResult(null);
    setConflict(null);
    setPage(1);
    setSearch("");
  }

  function chooseFolder(id: string) {
    setFolderId(id);
    setPage(1);
    setSelected(new Set());
    setResult(null);
    setConflict(null);
  }

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (m) =>
        (m.from_name ?? "").toLowerCase().includes(q) ||
        (m.from_addr ?? "").toLowerCase().includes(q) ||
        (m.subject ?? "").toLowerCase().includes(q),
    );
  }, [items, search]);

  const selectedVisible = visible.filter((m) => selected.has(m.id));
  const allChecked = visible.length > 0 && visible.every((m) => selected.has(m.id));
  const someChecked = selectedVisible.length > 0;
  const headRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (headRef.current) headRef.current.indeterminate = someChecked && !allChecked;
  }, [someChecked, allChecked]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const m of visible) {
        if (allChecked) next.delete(m.id);
        else next.add(m.id);
      }
      return next;
    });
  }

  const total = listing?.total ?? 0;
  const uidvalidity = listing?.uidvalidity ?? "";

  function askSelected() {
    if (!folderId || selectedVisible.length === 0) return;
    const ids = selectedVisible.map((m) => m.id);
    const n = ids.length;
    setPlan({
      folder: folderId,
      mode: "selected",
      ids,
      count: n,
      uidvalidity,
      title: n === 1 ? `1 Nachricht aus „${folderName}“ löschen?` : `${n} Nachrichten aus „${folderName}“ löschen?`,
      body: "Die ausgewählten Nachrichten werden auf dem Server gelöscht. Lotse prüft danach, ob sie wirklich entfernt wurden.",
    });
  }

  function askOne(m: MessageItem) {
    if (!folderId) return;
    setPlan({
      folder: folderId,
      mode: "selected",
      ids: [m.id],
      count: 1,
      uidvalidity,
      title: `1 Nachricht aus „${folderName}“ löschen?`,
      body: `${senderName(m)} · „${m.subject || "(kein Betreff)"}“`,
    });
  }

  function askFolder() {
    if (!folderId || total === 0) return;
    const gmail = account?.provider === "gmail";
    setPlan(
      onlyReg
        ? {
            folder: folderId,
            mode: "registration",
            ids: [],
            count: total,
            uidvalidity,
            title: `Alle ${formatNumber(total)} Registrierungs-Mails in „${folderName}“ löschen?`,
            body: gmail
              ? "Bei Gmail betrifft das alle als Registrierung erkannten Nachrichten dieses Postfachs – unabhängig vom Label, nicht nur die sichtbare Seite."
              : "Das betrifft jede als Registrierung erkannte Nachricht in diesem Ordner, nicht nur die sichtbare Seite.",
          }
        : {
            folder: folderId,
            mode: "all",
            ids: [],
            count: total,
            uidvalidity,
            title: `Alle ${formatNumber(total)} Nachrichten in „${folderName}“ löschen?`,
            body: "Das betrifft jede Nachricht in diesem Ordner, nicht nur die sichtbare Seite.",
          },
    );
  }

  function onDeleted(r: DeleteResult) {
    setPlan(null);
    setConflict(null);
    setResult(summarizeDeleteResult(r));
    setSelected(new Set());
    reloadAll();
  }

  function onConflict(message: string) {
    setPlan(null);
    setResult(null);
    setConflict(message);
    reloadAll();
  }

  const header = (
    <PageHeader
      title="E-Mails"
      intro="Einzelne, ausgewählte oder alle Mails eines Ordners löschen. Jede Löschung wird mit dem Server abgeglichen und überprüft."
      actions={
        accounts && accounts.length > 0 && account ? (
          <label className="field-compact">
            Postfach
            <select className="select select-wide" value={account.id} onChange={(e) => chooseAccount(Number(e.target.value))}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {accountOptionLabel(a)}
                </option>
              ))}
            </select>
          </label>
        ) : null
      }
    />
  );

  if (accountsError) {
    return (
      <div className="page">
        {header}
        <Banner kind="error" title="Postfächer konnten nicht geladen werden">
          {accountsError}
        </Banner>
      </div>
    );
  }
  if (!accounts) {
    return (
      <div className="page">
        {header}
        <Spinner />
      </div>
    );
  }
  if (!account) {
    return (
      <div className="page">
        {header}
        <div className="empty-card">
          <h2>Noch kein Postfach verbunden</h2>
          <p className="muted">Verbinde zuerst ein Postfach, um E-Mails zu verwalten.</p>
          <Link className="btn btn-primary" to="/verbindungen">
            Postfach verbinden
          </Link>
        </div>
      </div>
    );
  }

  const pages = listing ? totalPages(listing.total, listing.page_size) : 1;
  const folderBtnLabel = onlyReg ? "Alle Registrierungs-Mails löschen" : `Ordner „${folderName || "…"}“ leeren`;

  return (
    <div className="page page-tight">
      {header}

      {result ? (
        <Banner
          kind={result.ok ? "success" : "error"}
          title={result.headline}
          onClose={() => setResult(null)}
        >
          {result.ok && result.notes.length === 0 ? (
            <span className="muted">Server-Abgleich bestätigt: Die Nachrichten sind im Ordner nicht mehr vorhanden.</span>
          ) : (
            result.notes.map((n) => (
              <span key={n} className="block">
                {n}
              </span>
            ))
          )}
        </Banner>
      ) : null}
      {conflict ? (
        <Banner kind="warning" title="Der Ordner hat sich geändert" onClose={() => setConflict(null)}>
          {conflict} Die Liste wurde neu geladen – bitte erneut auswählen und bestätigen.
        </Banner>
      ) : null}

      <div className="mail-layout">
        <section aria-label="Ordner" className="folder-panel">
          {foldersError ? (
            <div className="stack-6 pad-8">
              <span className="text-red small">{foldersError}</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadFolders(false)}>
                Erneut versuchen
              </button>
            </div>
          ) : !folders ? (
            <Spinner label="Ordner werden geladen …" />
          ) : isPhone ? (
            <label className="field-compact folder-select">
              Ordner
              <select className="select" value={folderId ?? ""} onChange={(e) => chooseFolder(e.target.value)}>
                {folders.map((f) => (
                  <option key={f.id} value={f.id}>
                    {folderDisplayName(f)} ({formatNumber(f.count)})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            folders.map((f) => (
              <button
                key={f.id}
                type="button"
                className="folder-btn"
                aria-pressed={f.id === folderId}
                onClick={() => chooseFolder(f.id)}
              >
                <span className="truncate">{folderDisplayName(f)}</span>
                <span className="mono small muted">{formatNumber(f.count)}</span>
              </button>
            ))
          )}
        </section>

        <section aria-label="Nachrichten" className="messages-panel">
          <div className="toolbar">
            <label className="search">
              <Icon name="search" size={16} strokeWidth={2} className="muted-icon" />
              <span className="sr-only">Nachrichten auf dieser Seite durchsuchen</span>
              <input type="search" placeholder="Absender oder Betreff …" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
            <label className="toggle-box">
              <input
                type="checkbox"
                checked={onlyReg}
                onChange={(e) => {
                  setOnlyReg(e.target.checked);
                  setPage(1);
                  setResult(null);
                }}
              />
              Nur Registrierungs-Mails
            </label>
          </div>

          <div className="action-bar">
            <label className="check-row">
              <input ref={headRef} type="checkbox" checked={allChecked} onChange={toggleAll} disabled={visible.length === 0} />
              <span>
                {selectedVisible.length
                  ? `${selectedVisible.length} von ${visible.length} ausgewählt`
                  : `Alle ${visible.length} auswählen`}
              </span>
            </label>
            <div className="action-bar-buttons">
              <button type="button" className="btn btn-danger-outline btn-sm" disabled={selectedVisible.length === 0} onClick={askSelected}>
                Ausgewählte löschen
              </button>
              <button type="button" className="btn btn-danger btn-sm" disabled={!listing || total === 0 || listLoading} onClick={askFolder}>
                {folderBtnLabel}
              </button>
            </div>
          </div>

          {listError ? (
            <Banner kind="error" title="Nachrichten konnten nicht geladen werden">
              {listError}{" "}
              <button type="button" className="link-btn" onClick={() => setReloadKey((k) => k + 1)}>
                Erneut versuchen
              </button>
            </Banner>
          ) : null}

          <div className="table-box" aria-busy={listLoading}>
            <div className="mail-table">
              {listLoading && items.length === 0 ? <Spinner label="Nachrichten werden geladen …" /> : null}
              {visible.map((m) => {
                const cat = categoryLabel(m.category);
                const checked = selected.has(m.id);
                const name = senderName(m);
                return (
                  <div key={m.id} className={`mail-row${checked ? " selected" : ""}`}>
                    <label className="check-cell mail-check">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(m.id)}
                        aria-label={`${name}: ${m.subject || "(kein Betreff)"} auswählen`}
                      />
                    </label>
                    <span className="mail-from truncate" title={m.from_addr || undefined}>
                      {name}
                    </span>
                    <span className="mail-subject muted truncate">{m.subject || "(kein Betreff)"}</span>
                    <span className="mail-cat">{cat ? <span className="badge badge-blue">{cat}</span> : null}</span>
                    <span className="mail-date mono small muted">{formatDate(m.date)}</span>
                    <button type="button" className="icon-btn mail-del" onClick={() => askOne(m)} aria-label={`Nachricht von ${name} löschen`}>
                      <Icon name="trash" />
                    </button>
                  </div>
                );
              })}
              {!listLoading && listing && visible.length === 0 ? (
                <div className="empty-row">
                  {items.length > 0
                    ? "Keine Nachricht auf dieser Seite passt zur Suche."
                    : onlyReg
                      ? "Keine Registrierungs-Mails in diesem Ordner."
                      : "Dieser Ordner ist leer."}
                </div>
              ) : null}
            </div>
          </div>

          {listing ? (
            cursorMode ? (
              <div className="pager">
                <span className="muted small">
                  {formatNumber(items.length)} von {total ? `ca. ${formatNumber(total)}` : "?"} geladen
                </span>
                {listing.next_cursor ? (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadMore()} disabled={moreLoading}>
                    {moreLoading ? "Wird geladen …" : "Weitere laden"}
                  </button>
                ) : null}
              </div>
            ) : pages > 1 ? (
              <nav className="pager" aria-label="Seiten">
                <button
                  type="button"
                  className="icon-btn icon-btn-bordered"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || listLoading}
                  aria-label="Vorherige Seite"
                >
                  <Icon name="chevronLeft" />
                </button>
                {pageTokens(page, pages).map((t, i) =>
                  t === "gap" ? (
                    <span key={`g${i}`} className="muted" aria-hidden="true">
                      …
                    </span>
                  ) : (
                    <button
                      key={t}
                      type="button"
                      className="page-btn"
                      aria-current={t === page ? "page" : undefined}
                      aria-label={`Seite ${t}`}
                      onClick={() => setPage(t)}
                      disabled={listLoading}
                    >
                      {t}
                    </button>
                  ),
                )}
                <button
                  type="button"
                  className="icon-btn icon-btn-bordered"
                  onClick={() => setPage((p) => Math.min(pages, p + 1))}
                  disabled={page >= pages || listLoading}
                  aria-label="Nächste Seite"
                >
                  <Icon name="chevronRight" />
                </button>
                <span className="muted small">{formatNumber(total)} Nachrichten</span>
              </nav>
            ) : (
              <div className="pager">
                <span className="muted small">{formatNumber(total)} Nachrichten</span>
              </div>
            )
          ) : null}

          <p className="muted small no-margin">
            Lotse zeigt nur Absender, Betreff und Datum. Mail-Inhalte werden weder gespeichert noch protokolliert. Die Suche
            filtert nur die geladene Seite.
          </p>
        </section>
      </div>

      {plan && account ? (
        <DeleteDialog
          plan={plan}
          accountId={account.id}
          provider={account.provider}
          folderSpecial={folder?.special ?? ""}
          onCancel={() => setPlan(null)}
          onDone={onDeleted}
          onConflict={onConflict}
        />
      ) : null}
    </div>
  );
}
