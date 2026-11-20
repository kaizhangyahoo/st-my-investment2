import React, { useState, useEffect, useMemo } from 'react';
import { tickersApi, apiErrorMessage } from '../../services/api';
import { UnresolvedSymbol } from '../../types';

interface TickerMappingViewProps {
  unresolvedSymbols?: UnresolvedSymbol[];
  onMappingsChanged?: () => void;
}

interface MappingRow {
  id: number;
  origName: string;
  origTicker: string;
  name: string;
  ticker: string;
  deleted: boolean;
}

interface PendingDraft {
  ticker: string;
  touched: boolean;
}

type Status = { tone: 'ok' | 'error'; text: string } | null;

// Mirrors the backend's near-duplicate check: case and whitespace runs are ignored.
const fold = (name: string) => name.trim().split(/\s+/).join(' ').toLowerCase();

const toRows = (mappings: Record<string, string>): MappingRow[] =>
  Object.entries(mappings).map(([name, ticker], id) => ({
    id,
    origName: name,
    origTicker: ticker,
    name,
    ticker,
    deleted: false,
  }));

const isChanged = (r: MappingRow) => r.deleted || r.name !== r.origName || r.ticker !== r.origTicker;

export const TickerMappingView: React.FC<TickerMappingViewProps> = ({
  unresolvedSymbols = [],
  onMappingsChanged,
}) => {
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [newKey, setNewKey] = useState('');
  const [newVal, setNewVal] = useState('');
  const [status, setStatus] = useState<Status>(null);
  const [resolving, setResolving] = useState(false);
  const [suggestFailed, setSuggestFailed] = useState(false);
  const [resolveResults, setResolveResults] = useState<Record<string, string | null>>({});
  const [pendingDrafts, setPendingDrafts] = useState<Record<string, PendingDraft>>({});
  const [editing, setEditing] = useState(false);
  const [editRows, setEditRows] = useState<MappingRow[]>([]);
  const [saving, setSaving] = useState(false);

  const flash = (tone: 'ok' | 'error', text: string) => {
    setStatus({ tone, text });
    if (tone === 'ok') setTimeout(() => setStatus((s) => (s?.text === text ? null : s)), 3000);
  };

  const loadMappings = async () => {
    setLoading(true);
    try {
      const data = await tickersApi.getMappings();
      setMappings(data);
      return data;
    } catch (err) {
      console.error('Failed to load mappings', err);
      flash('error', apiErrorMessage(err, 'Failed to load mappings'));
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMappings();
  }, []);

  // Names the backend reported unresolved that the stored map still doesn't cover, so a
  // just-saved name drops out before the parent's summary refresh lands.
  const pending = unresolvedSymbols.filter((s) => !mappings[s.market_name]?.trim());

  const requestSuggestions = (names: string[]) => {
    let cancelled = false;
    setResolving(true);
    setSuggestFailed(false);
    tickersApi
      .resolve(names)
      .then((res) => {
        if (cancelled) return;
        setResolveResults((prev) => ({ ...prev, ...res }));
        // Never overwrite a ticker the user has already typed.
        setPendingDrafts((prev) => {
          const next = { ...prev };
          for (const [name, ticker] of Object.entries(res)) {
            if (ticker && !next[name]?.touched) next[name] = { ticker, touched: false };
          }
          return next;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('SEC resolution failed', err);
        setSuggestFailed(true);
      })
      .finally(() => {
        if (!cancelled) setResolving(false);
      });
    return () => {
      cancelled = true;
    };
  };

  // Suggestions load as soon as unresolved names arrive; no manual resolver click needed.
  // Names already queried are skipped, so a summary refresh after a partial save doesn't
  // send the survivors back to SEC.
  const unresolvedKey = unresolvedSymbols.map((s) => s.market_name).join('|');
  useEffect(() => {
    const names = unresolvedSymbols.map((s) => s.market_name).filter((n) => !(n in resolveResults));
    if (names.length === 0) return;
    return requestSuggestions(names);
  }, [unresolvedKey]);

  const setPendingTicker = (name: string, ticker: string) =>
    setPendingDrafts((prev) => ({ ...prev, [name]: { ticker: ticker.toUpperCase(), touched: true } }));

  // Merge-mode save: only the given entries are written, the rest of the file is kept.
  const commitMerge = async (entries: Record<string, string>, successText: string) => {
    setSaving(true);
    try {
      const saved = await tickersApi.updateMappings(entries);
      setMappings(saved);
      flash('ok', successText);
      onMappingsChanged?.();
      return true;
    } catch (err) {
      flash('error', apiErrorMessage(err, 'Failed to save mapping'));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const pendingToSave: Record<string, string> = {};
  for (const { market_name } of pending) {
    const ticker = pendingDrafts[market_name]?.ticker.trim();
    if (ticker) pendingToSave[market_name] = ticker;
  }
  const pendingSaveCount = Object.keys(pendingToSave).length;

  const handleSaveOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = newKey.trim();
    const val = newVal.trim().toUpperCase();
    if (!key || !val) return;
    if (key in mappings && mappings[key] !== val) {
      if (!window.confirm(`"${key}" is already mapped to ${mappings[key]}. Overwrite with ${val}?`)) return;
    }
    if (await commitMerge({ [key]: val }, 'MAPPING COMMITTED TO DISK (company_name_to_ticker.json)')) {
      setNewKey('');
      setNewVal('');
    }
  };

  // ── Resolver Editor ──────────────────────────────────────────────
  const rowErrors = useMemo(() => {
    const errors: Record<number, string> = {};
    const seen = new Map<string, string>();
    for (const r of editRows) {
      if (r.deleted) continue;
      const name = r.name.trim();
      if (!name) {
        errors[r.id] = 'Name is blank';
      } else if (!r.ticker.trim()) {
        errors[r.id] = 'Ticker is blank';
      } else if (seen.has(fold(name))) {
        errors[r.id] = `Duplicates "${seen.get(fold(name))}"`;
      } else {
        seen.set(fold(name), name);
      }
    }
    return errors;
  }, [editRows]);

  const changeCount = editRows.filter(isChanged).length;
  const deleteCount = editRows.filter((r) => r.deleted).length;
  const errorCount = Object.keys(rowErrors).length;

  const toggleEditor = async () => {
    if (editing) {
      if (changeCount > 0 && !window.confirm(`Discard ${changeCount} unsaved change(s)?`)) return;
      setEditing(false);
      setEditRows([]);
      return;
    }
    // The editor saves the whole map, so start from what is on disk right now.
    const latest = await loadMappings();
    if (!latest) return;
    setEditRows(toRows(latest));
    setEditing(true);
  };

  const updateRow = (id: number, patch: Partial<MappingRow>) =>
    setEditRows((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const handleSaveEdits = async () => {
    if (errorCount > 0 || changeCount === 0) return;
    if (
      deleteCount > 0 &&
      !window.confirm(`Save ${changeCount} change(s)? ${deleteCount} mapping(s) will be removed from disk.`)
    )
      return;
    const next: Record<string, string> = {};
    for (const r of editRows) {
      if (!r.deleted) next[r.name.trim()] = r.ticker.trim().toUpperCase();
    }
    setSaving(true);
    try {
      const saved = await tickersApi.replaceMappings(next);
      setMappings(saved);
      setEditing(false);
      setEditRows([]);
      flash('ok', `${changeCount} CHANGE(S) COMMITTED TO DISK (company_name_to_ticker.json)`);
      onMappingsChanged?.();
    } catch (err) {
      flash('error', apiErrorMessage(err, 'Failed to save edits'));
    } finally {
      setSaving(false);
    }
  };

  const viewRows = useMemo(() => toRows(mappings), [mappings]);
  const tableRows = editing ? editRows : viewRows;
  const filteredRows = tableRows.filter(
    (r) =>
      r.name.toLowerCase().includes(search.toLowerCase()) ||
      r.ticker.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-space-lg pb-16">
      {/* ─────────────────────────────────────────────────────────────
          1. WORKSPACE SUB-HEADER & TELEMETRY STRIP
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-space-md">
        <div className="flex items-center gap-space-sm">
          <span className="material-symbols-outlined text-[20px] text-secondary">tune</span>
          <div>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Reference Data & Instrument Taxonomy Master
            </span>
            <span className="font-label-caps text-[10px] text-outline block">
              STORAGE: company_name_to_ticker.json • RECONCILIATION ENGINE
            </span>
          </div>
        </div>

        {/* Quick Action Toolbar */}
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            onClick={() => requestSuggestions(pending.map((s) => s.market_name))}
            disabled={resolving || pending.length === 0}
            title={
              pending.length === 0
                ? 'No unmapped symbols in the loaded trade history'
                : `Re-query SEC EDGAR for ${pending.length} unmapped symbol(s)`
            }
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-surface-container-highest hover:bg-surface-container text-secondary text-xs font-mono font-medium transition-colors border border-secondary/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span className={`material-symbols-outlined text-[15px] ${resolving ? 'animate-spin' : ''}`}>
              {resolving ? 'progress_activity' : 'travel_explore'}
            </span>
            <span>
              {resolving
                ? 'QUERYING SEC...'
                : `RE-RUN SEC RESOLVER${pending.length > 0 ? ` (${pending.length})` : ''}`}
            </span>
          </button>
          <button
            type="button"
            onClick={toggleEditor}
            disabled={loading || saving}
            aria-pressed={editing}
            title={editing ? 'Leave the editor (unsaved changes are discarded)' : 'Edit, rename or delete stored mappings'}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono transition-colors border disabled:opacity-40 ${
              editing
                ? 'bg-primary-container text-on-primary-container border-primary font-bold'
                : 'bg-surface-container-low hover:bg-surface-container text-on-surface border-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">{editing ? 'edit_off' : 'edit'}</span>
            <span>RESOLVER EDITOR{editing ? ': ON' : ''}</span>
          </button>
        </div>
      </div>

      {status && (
        <div
          role={status.tone === 'error' ? 'alert' : 'status'}
          className={`text-[11px] font-mono p-2 rounded border ${
            status.tone === 'error'
              ? 'text-error bg-error/10 border-error/20'
              : 'text-primary bg-primary/10 border-primary/20'
          }`}
        >
          {status.text}
        </div>
      )}

      {/* Telemetry Stats Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm">
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Active Mapped Taxonomy</span>
          <span className="font-data-mono-lg text-sm text-primary font-bold my-1 block">
            {Object.keys(mappings).length} Stored Pairs
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">
            {pending.length === 0 ? 'Covers loaded history' : 'Incomplete coverage'}
          </span>
        </div>
        <div
          className={`p-3 rounded-lg border shadow-sm ${
            pending.length > 0
              ? 'bg-error-container/20 border-error/40'
              : 'bg-surface-container-low border-surface-container/60'
          }`}
        >
          <span className="font-label-caps text-[10px] text-outline uppercase block">Pending Ingestion</span>
          <span
            className={`font-data-mono-lg text-sm font-bold my-1 block ${
              pending.length > 0 ? 'text-error' : 'text-primary'
            }`}
          >
            {pending.length} Unresolved
          </span>
          <span
            className={`font-data-mono-sm text-[10px] ${
              pending.length > 0 ? 'text-error' : 'text-outline'
            }`}
          >
            {pending.length > 0
              ? `${pending.reduce((a, s) => a + s.row_count, 0)} trade rows excluded`
              : 'Loaded history fully mapped'}
          </span>
        </div>
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Ingestion Source</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1 block">
            IG & T212 Statement Feeds
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">Live Linked</span>
        </div>
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Taxonomy Audit</span>
          <span
            className={`font-data-mono-lg text-sm font-bold my-1 block ${
              changeCount > 0 ? 'text-secondary' : 'text-primary'
            }`}
          >
            {changeCount > 0 ? `${changeCount} UNSAVED EDIT(S)` : 'SYNCED TO DISK'}
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">JSON Store Active</span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          2. PENDING RESOLUTION SECTION (SEC suggestions pre-loaded)
      ───────────────────────────────────────────────────────────── */}
      {pending.length > 0 && (
        <div className="p-space-md rounded-xl bg-surface-container-low border border-error/40 shadow-sm space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-space-xs border-b border-surface-container/40">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-error">notification_important</span>
              <span className="font-headline-md text-sm text-on-surface font-semibold">
                Unmapped Symbols in Loaded Trade History
              </span>
              <span className="font-data-mono-sm text-[10px] text-secondary flex items-center gap-1">
                {resolving && 'QUERYING SEC EDGAR...'}
                {!resolving && suggestFailed && 'SEC UNAVAILABLE — ENTER TICKERS MANUALLY'}
              </span>
            </div>
            <button
              type="button"
              onClick={() => commitMerge(pendingToSave, `${pendingSaveCount} MAPPING(S) COMMITTED TO DISK`)}
              disabled={saving || editing || pendingSaveCount === 0}
              title={editing ? 'Leave the Resolver Editor before saving suggestions' : undefined}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              <span className="material-symbols-outlined text-[15px]">save</span>
              <span>SAVE {pendingSaveCount} MAPPING{pendingSaveCount === 1 ? '' : 'S'}</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
            {pending.map(({ market_name: name, row_count }) => {
              const draft = pendingDrafts[name]?.ticker ?? '';
              const suggested = resolveResults[name];
              return (
                <div
                  key={name}
                  className="p-3 rounded bg-surface-container-lowest border border-surface-container/50 flex items-center justify-between gap-2"
                >
                  <div className="min-w-0 flex-1">
                    <span className="font-body-sm text-xs text-on-surface font-medium block truncate">{name}</span>
                    <span className="font-data-mono-sm text-[10px] text-outline block">
                      {row_count} trade row{row_count === 1 ? '' : 's'} excluded
                      {name in resolveResults && ` • SEC: ${suggested || 'NO MATCH'}`}
                    </span>
                  </div>
                  <input
                    type="text"
                    value={draft}
                    onChange={(e) => setPendingTicker(name, e.target.value)}
                    placeholder="e.g. MMM"
                    aria-label={`Ticker for ${name}`}
                    className="w-24 px-2 py-1 rounded bg-surface-container border border-surface-container text-xs font-mono font-bold text-primary focus:outline-none focus:border-primary"
                  />
                  <button
                    type="button"
                    onClick={() => commitMerge({ [name]: draft.trim() }, `${name} → ${draft.trim()} COMMITTED`)}
                    disabled={saving || editing || !draft.trim()}
                    className="px-2.5 py-1 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    ACCEPT
                  </button>
                </div>
              );
            })}
          </div>

          <p className="font-body-sm text-[11px] text-on-surface-variant">
            Names left unsaved are excluded from positions and P&amp;L. You will be prompted again on the next upload.
          </p>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          3. ACTIVE SYMBOL MAPPINGS TABLE & LIVE JSON INSPECTOR
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Active Mappings Table (8 cols) */}
        <div
          className={`xl:col-span-8 bg-surface-container-low p-space-md rounded-xl border shadow-sm ${
            editing ? 'border-primary/50' : 'border-surface-container/60'
          }`}
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">data_object</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Active Symbol Mappings
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-caps text-[10px]">
                {filteredRows.length} OF {tableRows.length}
              </span>
              {editing && (
                <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-label-caps text-[10px] font-bold">
                  EDITING
                </span>
              )}
            </div>

            <div className="relative">
              <span className="material-symbols-outlined absolute left-2 top-2 text-[15px] text-outline">
                search
              </span>
              <input
                type="text"
                placeholder="Search raw name or ticker..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-7 pr-3 py-1 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary w-52"
              />
            </div>
          </div>

          {editing && (
            <div className="flex flex-wrap items-center justify-between gap-2 mb-space-sm p-2 rounded bg-surface-container-lowest border border-surface-container/50">
              <span className={`font-data-mono-sm text-[11px] ${errorCount > 0 ? 'text-error' : 'text-on-surface-variant'}`}>
                {errorCount > 0
                  ? `${errorCount} row(s) need fixing before saving`
                  : `${changeCount} pending change(s)${deleteCount > 0 ? `, ${deleteCount} delete(s)` : ''}`}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleEditor}
                  disabled={saving}
                  className="px-3 py-1 rounded bg-surface-container-low hover:bg-surface-container text-on-surface-variant text-xs font-mono transition-colors border border-surface-container disabled:opacity-50"
                >
                  DISCARD
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdits}
                  disabled={saving || changeCount === 0 || errorCount > 0}
                  className="flex items-center gap-1 px-3 py-1 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <span className="material-symbols-outlined text-[15px]">save</span>
                  <span>{saving ? 'SAVING...' : 'SAVE CHANGES'}</span>
                </button>
              </div>
            </div>
          )}

          <div className="overflow-x-auto max-h-[500px]">
            <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
              <thead className="sticky top-0 bg-surface-container-low z-10">
                <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                  <th className="py-2 px-space-sm">CSV Raw String / Broker Feed</th>
                  <th className="py-2 px-space-sm">Mapped Ticker</th>
                  <th className="py-2 px-space-sm">Exchange / MIC</th>
                  <th className="py-2 px-space-sm">Status</th>
                  {editing && <th className="py-2 px-space-sm text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container/30">
                {filteredRows.map((row) => {
                  const { id, name, ticker, deleted } = row;
                  const isLondon = ticker.endsWith('.L');
                  const isGermany = ticker.endsWith('.DE');
                  const mic = isLondon ? 'XLON (LSE)' : isGermany ? 'XETR (Xetra)' : 'XNYS / XNAS';
                  // A ticker that is itself a key resolves onwards via a corporate-action chain.
                  const isRemapped = ticker in mappings;
                  const isBlank = !ticker.trim();
                  const error = editing ? rowErrors[id] : undefined;
                  return (
                    <tr key={id} className={`hover:bg-surface-container-high/40 ${deleted ? 'bg-error/5' : ''}`}>
                      <td className="py-2.5 px-space-sm text-on-surface font-medium truncate max-w-[240px]">
                        {editing ? (
                          <input
                            type="text"
                            value={name}
                            onChange={(e) => updateRow(id, { name: e.target.value })}
                            disabled={deleted}
                            aria-label={`Name for ${row.origName}`}
                            className={`w-full px-2 py-1 rounded bg-surface-container-lowest border text-xs font-mono text-on-surface focus:outline-none focus:border-primary ${
                              error ? 'border-error' : 'border-surface-container'
                            } ${deleted ? 'line-through opacity-50' : ''}`}
                          />
                        ) : (
                          name
                        )}
                      </td>
                      <td className="py-2.5 px-space-sm font-bold text-primary">
                        {editing ? (
                          <input
                            type="text"
                            value={ticker}
                            onChange={(e) => updateRow(id, { ticker: e.target.value.toUpperCase() })}
                            disabled={deleted}
                            aria-label={`Ticker for ${row.origName}`}
                            className={`w-28 px-2 py-1 rounded bg-surface-container-lowest border text-xs font-mono font-bold text-primary focus:outline-none focus:border-primary ${
                              error ? 'border-error' : 'border-surface-container'
                            } ${deleted ? 'line-through opacity-50' : ''}`}
                          />
                        ) : (
                          ticker
                        )}
                      </td>
                      <td className="py-2.5 px-space-sm text-outline">
                        {mic}
                      </td>
                      <td className="py-2.5 px-space-sm">
                        {deleted ? (
                          <span className="px-1.5 py-0.5 rounded bg-error/10 text-error border border-error/20 text-[10px] font-bold">
                            DELETE
                          </span>
                        ) : error ? (
                          <span
                            className="px-1.5 py-0.5 rounded bg-error/10 text-error border border-error/20 text-[10px] font-bold"
                            title={error}
                          >
                            {error.toUpperCase()}
                          </span>
                        ) : editing && isChanged(row) ? (
                          <span className="px-1.5 py-0.5 rounded bg-secondary/10 text-secondary border border-secondary/20 text-[10px] font-bold">
                            EDITED
                          </span>
                        ) : isBlank ? (
                          <span className="px-1.5 py-0.5 rounded bg-error/10 text-error border border-error/20 text-[10px] font-bold">
                            BLANK
                          </span>
                        ) : isRemapped ? (
                          <span
                            className="px-1.5 py-0.5 rounded bg-secondary/10 text-secondary border border-secondary/20 text-[10px] font-bold"
                            title={`Resolves onwards via ${ticker} → ${mappings[ticker]}`}
                          >
                            REMAPPED
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 text-[10px] font-bold">
                            MAPPED
                          </span>
                        )}
                      </td>
                      {editing && (
                        <td className="py-2.5 px-space-sm text-right">
                          <button
                            type="button"
                            onClick={() => updateRow(id, { deleted: !deleted })}
                            className="px-2 py-0.5 rounded hover:bg-error-container/20 text-outline hover:text-error text-xs font-mono transition-colors"
                            title={deleted ? 'Restore mapping' : 'Mark mapping for deletion'}
                          >
                            <span className="material-symbols-outlined text-[15px]">
                              {deleted ? 'restore_from_trash' : 'delete'}
                            </span>
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Live JSON Store & Add Override Form (4 cols) */}
        <div className="xl:col-span-4 space-y-space-md">
          {/* Add Override Form */}
          <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
            <span className="font-headline-md text-sm text-on-surface font-semibold flex items-center gap-1.5 mb-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">add_circle</span>
              Add Custom Ticker Override
            </span>

            <form onSubmit={handleSaveOverride} className="space-y-3">
              <div>
                <label className="block font-label-caps text-[10px] text-outline uppercase mb-1">
                  Raw Broker Ingestion String
                </label>
                <input
                  type="text"
                  placeholder="e.g. Palantir Technologies Inc"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  className="w-full px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary"
                  required
                />
              </div>

              <div>
                <label className="block font-label-caps text-[10px] text-outline uppercase mb-1">
                  Resolved Yahoo Finance Symbol
                </label>
                <input
                  type="text"
                  placeholder="e.g. PLTR or SDR.L"
                  value={newVal}
                  onChange={(e) => setNewVal(e.target.value)}
                  className="w-full px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-primary font-bold focus:outline-none focus:border-primary"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={saving || editing}
                title={editing ? 'Leave the Resolver Editor before adding an override' : undefined}
                className="w-full py-1.5 rounded bg-primary-container hover:bg-primary font-bold text-on-primary-container text-xs font-mono transition-colors shadow-sm flex items-center justify-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span className="material-symbols-outlined text-[15px]">save</span>
                <span>COMMIT OVERRIDE</span>
              </button>
            </form>
          </div>

          {/* Live JSON Inspector */}
          <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
            <div className="flex items-center justify-between pb-space-xs mb-space-xs border-b border-surface-container/40">
              <span className="font-headline-md text-sm text-on-surface font-semibold flex items-center gap-1">
                <span className="material-symbols-outlined text-[16px] text-secondary">code</span>
                Live JSON Store
              </span>
              <span className="font-label-caps text-[10px] text-outline uppercase">
                company_name_to_ticker.json
              </span>
            </div>

            <pre className="p-space-sm rounded bg-surface-container-lowest border border-surface-container/40 text-[11px] font-mono text-on-surface-variant overflow-y-auto max-h-56">
              {JSON.stringify(mappings, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
