import React, { useEffect, useMemo, useState } from 'react';
import { Modal } from '../common/Modal';
import { tickersApi } from '../../services/api';
import { UnresolvedSymbol } from '../../types';

interface UnresolvedSymbolsModalProps {
  open: boolean;
  symbols: UnresolvedSymbol[];
  onResolved: () => void;
  onSkip: () => void;
}

interface DraftRow {
  ticker: string;
  include: boolean;
  touched: boolean;
}

export const UnresolvedSymbolsModal: React.FC<UnresolvedSymbolsModalProps> = ({
  open,
  symbols,
  onResolved,
  onSkip,
}) => {
  const [drafts, setDrafts] = useState<Record<string, DraftRow>>({});
  const [suggesting, setSuggesting] = useState(false);
  const [suggestFailed, setSuggestFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const names = useMemo(() => symbols.map((s) => s.market_name), [symbols]);
  const namesKey = names.join('|');

  useEffect(() => {
    if (!open || names.length === 0) return;

    setDrafts(
      Object.fromEntries(names.map((n) => [n, { ticker: '', include: true, touched: false }]))
    );
    setSaveError(null);
    setSuggestFailed(false);

    // Suggestions fill in behind the already-visible table; SEC is slow and may
    // return nothing, so manual entry must never wait on it.
    let cancelled = false;
    setSuggesting(true);
    tickersApi
      .resolve(names)
      .then((res) => {
        if (cancelled) return;
        setDrafts((prev) => {
          const next = { ...prev };
          for (const [name, ticker] of Object.entries(res)) {
            if (!ticker || next[name]?.touched) continue;
            next[name] = { ...next[name], ticker };
          }
          return next;
        });
      })
      .catch(() => {
        if (!cancelled) setSuggestFailed(true);
      })
      .finally(() => {
        if (!cancelled) setSuggesting(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, namesKey]);

  const setTicker = (name: string, ticker: string) =>
    setDrafts((prev) => ({
      ...prev,
      [name]: { ...prev[name], ticker: ticker.toUpperCase(), touched: true },
    }));

  const toggleInclude = (name: string) =>
    setDrafts((prev) => ({ ...prev, [name]: { ...prev[name], include: !prev[name].include } }));

  const pendingMappings = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [name, row] of Object.entries(drafts)) {
      if (row.include && row.ticker.trim()) out[name] = row.ticker.trim();
    }
    return out;
  }, [drafts]);

  const resolvableCount = Object.keys(pendingMappings).length;
  const affectedRows = symbols.reduce((acc, s) => acc + s.row_count, 0);

  const handleConfirm = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await tickersApi.updateMappings(pendingMappings);
      onResolved();
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to save mappings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title="Unmapped Symbols Need Resolution"
      subtitle={`${symbols.length} instrument name${symbols.length === 1 ? '' : 's'} across ${affectedRows} trade row${affectedRows === 1 ? '' : 's'} cannot be resolved to a ticker. Trades left unmapped are excluded from positions and P&L.`}
      onDismiss={onSkip}
      footer={
        <>
          {saveError && (
            <span className="font-data-mono-sm text-[11px] text-error mr-auto">{saveError}</span>
          )}
          <button
            type="button"
            onClick={onSkip}
            disabled={saving}
            className="px-3 py-1.5 rounded bg-surface-container-low hover:bg-surface-container text-on-surface-variant text-xs font-mono transition-colors border border-surface-container disabled:opacity-50"
          >
            SKIP FOR NOW
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={saving || resolvableCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined text-[15px]">save</span>
            <span>
              {saving ? 'SAVING...' : `SAVE ${resolvableCount} MAPPING${resolvableCount === 1 ? '' : 'S'} & CONTINUE`}
            </span>
          </button>
        </>
      }
    >
      <div className="flex items-center justify-between mb-space-sm">
        <span className="font-label-caps text-[10px] text-outline uppercase">
          Storage: company_name_to_ticker.json
        </span>
        <span className="font-data-mono-sm text-[10px] text-secondary flex items-center gap-1">
          {suggesting && (
            <>
              <span className="material-symbols-outlined text-[13px] animate-spin">progress_activity</span>
              QUERYING SEC EDGAR...
            </>
          )}
          {!suggesting && suggestFailed && 'SEC UNAVAILABLE — ENTER TICKERS MANUALLY'}
          {!suggesting && !suggestFailed && 'SUGGESTIONS LOADED'}
        </span>
      </div>

      <div className="overflow-x-auto border border-surface-container/50 rounded-lg">
        <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
          <thead className="bg-surface-container-lowest sticky top-0">
            <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
              <th className="py-2 px-space-sm">Broker Market Name</th>
              <th className="py-2 px-space-sm w-20 text-right">Rows</th>
              <th className="py-2 px-space-sm w-44">Yahoo Ticker</th>
              <th className="py-2 px-space-sm w-24 text-center">Include</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-container/30">
            {symbols.map(({ market_name, row_count }) => {
              const row = drafts[market_name];
              return (
                <tr key={market_name} className="hover:bg-surface-container-high/30">
                  <td className="py-2 px-space-sm text-on-surface font-medium">{market_name}</td>
                  <td className="py-2 px-space-sm text-right text-on-surface-variant">{row_count}</td>
                  <td className="py-2 px-space-sm">
                    <input
                      type="text"
                      value={row?.ticker ?? ''}
                      onChange={(e) => setTicker(market_name, e.target.value)}
                      placeholder="e.g. MMM"
                      disabled={!row?.include}
                      className="w-full px-2 py-1 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono font-bold text-primary focus:outline-none focus:border-primary disabled:opacity-40"
                    />
                  </td>
                  <td className="py-2 px-space-sm text-center">
                    <input
                      type="checkbox"
                      checked={row?.include ?? true}
                      onChange={() => toggleInclude(market_name)}
                      aria-label={`Include ${market_name}`}
                      className="w-4 h-4 accent-primary cursor-pointer"
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="font-body-sm text-[11px] text-on-surface-variant mt-space-sm">
        Unchecked or blank rows stay unmapped and their trades are excluded from the valuation. You
        will be prompted again next time these names appear.
      </p>
    </Modal>
  );
};
