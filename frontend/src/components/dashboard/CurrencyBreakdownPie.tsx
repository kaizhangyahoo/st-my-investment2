import React from 'react';
import { CurrencyAllocation } from '../../types';

interface CurrencySlice {
  code: string;
  label: string;
  gbp: number;
  text: string;
  dot: string;
}

export interface CurrencyAllocationModel {
  hasAllocation: boolean;
  total: number;
  slices: CurrencySlice[];
  unclassifiedGbp: number;
  hasUnclassified: boolean;
  classifiedPct: number;
  pct: (gbp: number) => number;
}

export const compactGbp = (v: number) =>
  Math.abs(v) >= 1000 ? `£${(v / 1000).toFixed(1)}k` : `£${v.toFixed(0)}`;

export function deriveCurrencyAllocation(
  allocation: CurrencyAllocation | undefined,
  enabled: boolean,
): CurrencyAllocationModel {
  const total = allocation?.total_gbp ?? 0;
  const hasAllocation = Boolean(allocation) && total > 0 && enabled;
  // Class names are literals, not interpolated: Tailwind only emits classes it can see in source.
  const slices = hasAllocation
    ? [
      { code: 'USD', label: 'US Dollar (USD)', gbp: allocation!.usd_gbp, text: 'text-primary', dot: 'bg-primary' },
      { code: 'GBP', label: 'British Pound (GBP)', gbp: allocation!.gbp, text: 'text-secondary', dot: 'bg-secondary' },
      { code: 'EUR', label: 'Euro (EUR)', gbp: allocation!.eur_gbp, text: 'text-tertiary-fixed', dot: 'bg-tertiary-fixed' },
    ].filter((s) => s.gbp !== 0)
    : [];
  // The engine buckets by the statement's Currency column but converts by ticker suffix, so a
  // holding in any other currency lands outside all three buckets. Show that gap, don't bury it.
  const unclassifiedGbp = hasAllocation
    ? total - slices.reduce((acc, s) => acc + s.gbp, 0)
    : 0;
  const pct = (gbp: number) => (total > 0 ? (gbp / total) * 100 : 0);

  return {
    hasAllocation,
    total,
    slices,
    unclassifiedGbp,
    hasUnclassified: hasAllocation && Math.abs(pct(unclassifiedGbp)) >= 0.5,
    classifiedPct: pct(total - unclassifiedGbp),
    pct,
  };
}

interface CurrencyBreakdownPieProps {
  model: CurrencyAllocationModel;
  isMissingTradeHistory: boolean;
  isShowingSamples: boolean;
}

export const CurrencyBreakdownPie: React.FC<CurrencyBreakdownPieProps> = ({
  model,
  isMissingTradeHistory,
  isShowingSamples,
}) => {
  const { hasAllocation, total, slices, unclassifiedGbp, hasUnclassified, classifiedPct, pct } = model;
  const isEmpty = isMissingTradeHistory || !hasAllocation;

  return (
    <>
      <div className="flex items-center justify-center py-4">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-40 text-center text-outline">
            <span className="material-symbols-outlined text-3xl mb-1 text-outline/50">pie_chart</span>
            <span className="font-mono text-xs">
              {isMissingTradeHistory ? 'Awaiting Trade History' : 'Allocation unavailable'}
            </span>
            <span className="text-[10px] text-outline/60 mt-0.5">
              {isMissingTradeHistory
                ? 'No holdings to allocate'
                : isShowingSamples
                  ? 'Not calculated for sample data'
                  : 'No priced holdings to allocate'}
            </span>
          </div>
        ) : (
          <div className="relative w-40 h-40">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
              {/* Background Track */}
              <path
                className="text-surface-container-highest"
                strokeWidth="4.5"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              {slices.map((s, i) => {
                const offset = slices
                  .slice(0, i)
                  .reduce((acc, prev) => acc + pct(prev.gbp), 0);
                return (
                  <path
                    key={s.code}
                    className={s.text}
                    strokeDasharray={`${pct(s.gbp).toFixed(2)}, 100`}
                    strokeDashoffset={(-offset).toFixed(2)}
                    strokeWidth="4.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                );
              })}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="font-data-mono-lg text-data-mono-lg font-bold text-on-surface">
                {compactGbp(total)}
              </span>
              <span className="font-label-caps text-[9px] text-outline uppercase">
                {classifiedPct.toFixed(0)}% Allocated
              </span>
            </div>
          </div>
        )}
      </div>

      {isEmpty ? (
        <div className="p-3 text-center text-outline font-mono text-xs bg-surface-container-lowest rounded border border-surface-container/30">
          {isMissingTradeHistory ? 'Awaiting TradeHistory*.csv' : 'No currency breakdown available'}
        </div>
      ) : (
        <div className="space-y-2 mt-2">
          {slices.map((s) => (
            <div
              key={s.code}
              className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30"
            >
              <div className="flex items-center gap-2">
                <div className={`w-2.5 h-2.5 rounded-full ${s.dot}`} />
                <span className="font-body-sm text-xs text-on-surface font-medium">{s.label}</span>
              </div>
              <span className="font-data-mono-sm text-xs text-on-surface">
                {pct(s.gbp).toFixed(1)}% • {compactGbp(s.gbp)}
              </span>
            </div>
          ))}
          {hasUnclassified && (
            <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full bg-outline" />
                <span
                  className="font-body-sm text-xs text-on-surface-variant font-medium"
                  title="Holdings whose statement currency is not USD, GBP or EUR"
                >
                  Other currencies
                </span>
              </div>
              <span className="font-data-mono-sm text-xs text-on-surface-variant">
                {pct(unclassifiedGbp).toFixed(1)}% • {compactGbp(unclassifiedGbp)}
              </span>
            </div>
          )}
        </div>
      )}
    </>
  );
};
