import React, { useEffect, useMemo, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { portfolioApi } from '../../services/api';
import { ChartTrade, PriceTradeChart } from './PriceTradeChart';
import { FeedStatus, PortfolioSummary, Position, TradeActivityItem, UploadResult } from '../../types';

interface IgAnalyticsViewProps {
  summary: PortfolioSummary | null;
  onReset: () => void;
  onUploadComplete: (res: UploadResult) => void;
  feed?: FeedStatus;
}

// Default institutional fallback dataset matching Stitch design
const SAMPLE_POSITIONS: Position[] = [
  { ticker: 'LRCX', market: 'Lam Research Corp', quantity: 24, current_price: 942.10, market_value_gbp: 17462.80, pnl_gbp: 4180.20, currency: 'USD' },
  { ticker: 'LITE', market: 'Lumentum Holdings Inc', quantity: 450, current_price: 54.30, market_value_gbp: 18882.15, pnl_gbp: 3410.50, currency: 'USD' },
  { ticker: 'NVDA', market: 'NVIDIA Corp', quantity: 180, current_price: 128.45, market_value_gbp: 17872.24, pnl_gbp: 6920.80, currency: 'USD' },
  { ticker: 'MMM', market: '3M Company', quantity: 160, current_price: 129.80, market_value_gbp: 16053.40, pnl_gbp: 1240.60, currency: 'USD' },
  { ticker: 'AAPL', market: 'Apple Inc', quantity: 95, current_price: 228.15, market_value_gbp: 16752.10, pnl_gbp: 2840.40, currency: 'USD' },
  { ticker: 'MSCI', market: 'MSCI Inc', quantity: 32, current_price: 588.40, market_value_gbp: 14550.20, pnl_gbp: 1980.10, currency: 'USD' },
  { ticker: 'SDR.L', market: 'Schroders PLC', quantity: 4200, current_price: 3.82, market_value_gbp: 16044.00, pnl_gbp: 860.00, currency: 'GBP' },
  { ticker: 'ISRG', market: 'Intuitive Surgical Inc', quantity: 35, current_price: 495.20, market_value_gbp: 13400.80, pnl_gbp: 2150.30, currency: 'USD' },
  { ticker: 'BL', market: 'BlackLine Inc', quantity: 120, current_price: 58.10, market_value_gbp: 5390.40, pnl_gbp: -640.20, currency: 'USD' },
  { ticker: 'FIRY', market: 'First Republic Trust Liquid', quantity: 80, current_price: 12.40, market_value_gbp: 768.00, pnl_gbp: -320.00, currency: 'USD' },
];

type ActivityPeriod = 'QUARTER' | 'YEAR' | 'ALL';
type ActivitySide = 'ALL' | 'BUY' | 'SELL';

const SESSION_SUFFIX = /\s*\((?:24 Hours|All Sessions|Extended Hours)\)\s*$/i;

// Backend sends ISO dates; older payloads may still carry IG's DD/MM/YYYY.
const parseActivityDate = (raw: string): Date | null => {
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(raw);
  if (iso) return new Date(+iso[1], +iso[2] - 1, +iso[3]);
  const dmy = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(raw);
  if (dmy) return new Date(+dmy[3], +dmy[2] - 1, +dmy[1]);
  return null;
};

const SAMPLE_TRADE_ACTIVITY: TradeActivityItem[] = [
  { qty: 40, fill: '$128.10', value: '£3,959.81', date: '2026-10-24', time: '14:22:04', activity: 'BUY', market: 'NVIDIA Corp (NVDA)' },
  { qty: 15, fill: '$938.50', value: '£10,878.02', date: '2026-10-18', time: '15:10:33', activity: 'BUY', market: 'Lam Research Corp (LRCX)' },
  { qty: 25, fill: '$130.40', value: '£2,519.32', date: '2026-10-12', time: '18:04:12', activity: 'SELL', market: '3M Company (MMM)' },
  { qty: 100, fill: '$53.90', value: '£4,165.38', date: '2026-09-28', time: '13:45:00', activity: 'BUY', market: 'Lumentum Holdings (LITE)' },
  { qty: 30, fill: '$224.50', value: '£5,204.80', date: '2026-09-14', time: '16:01:29', activity: 'BUY', market: 'Apple Inc (AAPL)' },
  { qty: 10, fill: '$592.10', value: '£4,575.73', date: '2026-09-02', time: '19:15:40', activity: 'SELL', market: 'MSCI Inc (MSCI)' },
];

export const IgAnalyticsView: React.FC<IgAnalyticsViewProps> = ({
  summary,
  onReset,
  onUploadComplete,
  feed = { state: 'live', detail: [] },
}) => {
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [activityPeriod, setActivityPeriod] = useState<ActivityPeriod>('QUARTER');
  const [activitySide, setActivitySide] = useState<ActivitySide>('ALL');
  const [instrumentQuery, setInstrumentQuery] = useState('');
  const [selectedInstrumentKey, setSelectedInstrumentKey] = useState<string | null>(null);
  const [showInstrumentSuggestions, setShowInstrumentSuggestions] = useState(false);
  const [highlightedSuggestion, setHighlightedSuggestion] = useState(-1);

  // File Upload via Dropzone
  const onDrop = async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const res = await portfolioApi.uploadFiles(acceptedFiles);
      if (res.errors && res.errors.length > 0) {
        setUploadError(res.errors.join(', '));
      } else {
        const fileNames = acceptedFiles.map((f) => f.name);
        setUploadedFiles(fileNames);
        onUploadComplete(res);
      }
    } catch (err: any) {
      setUploadError(err?.message || 'Failed to parse CSV statement');
    } finally {
      setIsUploading(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/csv': ['.csv'] },
  });

  // Resolve active displayed files (supports displaying multiple uploaded files)
  const activeFileList: string[] = [];
  if (uploadedFiles.length > 0) {
    activeFileList.push(...uploadedFiles);
  } else {
    if (summary?.source_file) activeFileList.push(summary.source_file);
    if (summary?.transaction_file) activeFileList.push(summary.transaction_file);
  }
  const displayedFileName =
    activeFileList.length > 0 ? activeFileList.join(' • ') : 'sample_trade_ledger_2026.csv';

  // Scenario B detection: transaction statement uploaded/present, but trade history is missing
  const isMissingTradeHistory = Boolean(
    summary?.missing_trade_history ||
    (uploadedFiles.length > 0 &&
      uploadedFiles.some((f) => /trans/i.test(f)) &&
      !uploadedFiles.some((f) => /trade/i.test(f)))
  );

  const unresolvedSymbols = summary?.unresolved_symbols ?? [];
  const hasExcludedRows = Boolean(summary?.excluded_row_count && unresolvedSymbols.length > 0);

  // Calculate or fallback data
  const hasLivePositions = summary && summary.positions && summary.positions.length > 0;
  // If trade history is missing (Scenario B), DO NOT load default demo dataset
  const positions = isMissingTradeHistory ? [] : (hasLivePositions ? summary.positions : SAMPLE_POSITIONS);

  const totalValue = isMissingTradeHistory
    ? 0
    : hasLivePositions
      ? summary.total_market_value_gbp
      : positions.reduce((acc, p) => acc + p.market_value_gbp, 0);

  const totalCost = isMissingTradeHistory
    ? 0
    : hasLivePositions
      ? summary.total_invested_cash
      : totalValue - positions.reduce((acc, p) => acc + p.pnl_gbp, 0);

  const totalPnl = isMissingTradeHistory
    ? 0
    : hasLivePositions
      ? summary.total_pnl_gbp
      : positions.reduce((acc, p) => acc + p.pnl_gbp, 0);

  const pnlPercent = totalCost > 0 ? ((totalPnl / totalCost) * 100).toFixed(1) : '0.0';

  // Filtered positions
  const filteredPositions = positions.filter(
    (p) =>
      p.ticker.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.market.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Filtered trade activity (live from summary or fallback sample)
  const tradeActivities = isMissingTradeHistory
    ? []
    : summary && summary.trade_activities && summary.trade_activities.length > 0
      ? summary.trade_activities
      : SAMPLE_TRADE_ACTIVITY;

  // Positions carry tickers for currently-held instruments; use them when an activity row has none.
  const tickerByMarket = new Map(positions.map((p) => [p.market, p.ticker]));
  const activityTicker = (item: TradeActivityItem) => item.ticker || tickerByMarket.get(item.market) || '';

  const now = new Date();
  const quarterIndex = Math.floor(now.getMonth() / 3);
  const quarterLabel = `Q${quarterIndex + 1} ${now.getFullYear()}`;
  const periodStart: Record<ActivityPeriod, Date | null> = {
    QUARTER: new Date(now.getFullYear(), quarterIndex * 3, 1),
    YEAR: new Date(now.getFullYear(), 0, 1),
    ALL: null,
  };
  const inPeriod = (item: TradeActivityItem, period: ActivityPeriod) => {
    const start = periodStart[period];
    if (!start) return true;
    const d = parseActivityDate(item.date);
    return d !== null && d >= start;
  };

  // IG lists one stock under several session variants, e.g. "Apple Inc (24 Hours)" and
  // "Apple Inc (All Sessions)". Group them by ticker (or by name without the session suffix)
  // so searching or picking an instrument returns trades from every variant.
  const baseNameOf = (market: string) => market.replace(SESSION_SUFFIX, '').trim();
  const tickerByBaseName = new Map<string, string>();
  tradeActivities.forEach((a) => {
    const t = activityTicker(a);
    if (t && !tickerByBaseName.has(baseNameOf(a.market))) tickerByBaseName.set(baseNameOf(a.market), t);
  });
  const instrumentKeyOf = (item: TradeActivityItem) => {
    const base = baseNameOf(item.market);
    return activityTicker(item) || tickerByBaseName.get(base) || base.toLowerCase();
  };

  const instrumentGroups = new Map<string, { key: string; label: string; ticker: string; variants: string[] }>();
  tradeActivities.forEach((a) => {
    const key = instrumentKeyOf(a);
    const group = instrumentGroups.get(key);
    if (!group) {
      const base = baseNameOf(a.market);
      instrumentGroups.set(key, {
        key,
        label: base,
        ticker: activityTicker(a) || tickerByBaseName.get(base) || '',
        variants: [a.market],
      });
    } else if (!group.variants.includes(a.market)) {
      group.variants.push(a.market);
    }
  });

  const normalizedQuery = instrumentQuery.trim().toLowerCase();
  const groupMatchesQuery = (g: { label: string; ticker: string; variants: string[] }) =>
    !normalizedQuery ||
    g.ticker.toLowerCase().includes(normalizedQuery) ||
    g.label.toLowerCase().includes(normalizedQuery) ||
    g.variants.some((v) => v.toLowerCase().includes(normalizedQuery));

  // Unique instruments across the whole ledger, so suggestions aren't limited by the period filter.
  const instrumentOptions = Array.from(instrumentGroups.values()).sort((a, b) => a.label.localeCompare(b.label));
  // After a pick the box holds a display label, not a query, so offer the full list to switch.
  const instrumentSuggestions = selectedInstrumentKey
    ? instrumentOptions
    : instrumentOptions.filter(groupMatchesQuery);
  const matchingInstrumentKeys = new Set(instrumentSuggestions.map((g) => g.key));

  const matchesInstrument = (item: TradeActivityItem) =>
    selectedInstrumentKey
      ? instrumentKeyOf(item) === selectedInstrumentKey
      : !normalizedQuery || matchingInstrumentKeys.has(instrumentKeyOf(item));

  const selectInstrument = (group: { key: string; label: string; ticker: string } | null) => {
    setInstrumentQuery(group ? (group.ticker ? `${group.label} (${group.ticker})` : group.label) : '');
    setSelectedInstrumentKey(group ? group.key : null);
    setShowInstrumentSuggestions(false);
    setHighlightedSuggestion(-1);
  };

  const instrumentActivities = tradeActivities.filter(matchesInstrument);
  const periodActivities = instrumentActivities.filter((a) => inPeriod(a, activityPeriod));
  const filteredActivity = periodActivities.filter(
    (a) => activitySide === 'ALL' || a.activity === activitySide
  );

  const selectedHolding = selectedTicker ? positions.find((p) => p.ticker === selectedTicker) || null : null;

  // Every ledger trade for the inspected instrument, across all IG session variants.
  const inspectorTrades = selectedHolding
    ? tradeActivities
      .filter((a) => instrumentKeyOf(a) === selectedHolding.ticker || baseNameOf(a.market) === baseNameOf(selectedHolding.market))
      .sort((a, b) => (b.date + b.time).localeCompare(a.date + a.time))
    : [];
  const inspectorTradesKey = inspectorTrades.map((t) => `${t.date}|${t.activity}|${t.qty}|${t.fill}`).join(';');

  // Average GBP paid per share across the recorded buys. Derived from the settled value rather
  // than `fill`, because IG quotes fills in minor units (25808.0 for $258.08) with no unit marker.
  const avgExecutionBasis = (() => {
    const buys = inspectorTrades
      .filter((t) => t.activity !== 'SELL')
      .map((t) => ({ qty: Math.abs(t.qty), settled: Math.abs(parseFloat(t.value.replace(/[^0-9.-]/g, ''))) }))
      .filter((t) => t.qty > 0 && Number.isFinite(t.settled) && t.settled > 0);
    if (buys.length === 0) return null;
    const qty = buys.reduce((acc, b) => acc + b.qty, 0);
    const settled = buys.reduce((acc, b) => acc + b.settled, 0);
    return `£${(settled / qty).toFixed(2)}`;
  })();
  const chartTrades = useMemo<ChartTrade[]>(
    () =>
      inspectorTrades.map((t) => {
        const d = parseActivityDate(t.date);
        const price = parseFloat(t.fill.replace(/[^0-9.-]/g, ''));
        return {
          date: d
            ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
            : t.date,
          side: t.activity === 'SELL' ? 'SELL' : 'BUY',
          qty: t.qty,
          price: Number.isFinite(price) && price > 0 ? price : null,
        };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [inspectorTradesKey]
  );

  useEffect(() => {
    if (!selectedHolding) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedTicker(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedHolding]);

  // Every figure on this page is a placeholder when this is true, so the status bar has to say so.
  const isShowingSamples = !isMissingTradeHistory && !hasLivePositions;

  const allocation = summary?.currency_allocation;
  const allocationTotal = allocation?.total_gbp ?? 0;
  const hasAllocation = Boolean(allocation) && allocationTotal > 0 && !isShowingSamples && !isMissingTradeHistory;
  // Class names are literals, not interpolated: Tailwind only emits classes it can see in source.
  const currencySlices = hasAllocation
    ? [
      { code: 'USD', label: 'US Dollar (USD)', gbp: allocation!.usd_gbp, text: 'text-primary', dot: 'bg-primary' },
      { code: 'GBP', label: 'British Pound (GBP)', gbp: allocation!.gbp, text: 'text-secondary', dot: 'bg-secondary' },
      { code: 'EUR', label: 'Euro (EUR)', gbp: allocation!.eur_gbp, text: 'text-tertiary-fixed', dot: 'bg-tertiary-fixed' },
    ].filter((s) => s.gbp !== 0)
    : [];
  // The engine buckets by the statement's Currency column but converts by ticker suffix, so a
  // holding in any other currency lands outside all three buckets. Show that gap, don't bury it.
  const unclassifiedGbp = hasAllocation
    ? allocationTotal - currencySlices.reduce((acc, s) => acc + s.gbp, 0)
    : 0;
  const allocationPct = (gbp: number) => (allocationTotal > 0 ? (gbp / allocationTotal) * 100 : 0);
  const classifiedPct = allocationPct(allocationTotal - unclassifiedGbp);
  const hasUnclassified = hasAllocation && Math.abs(allocationPct(unclassifiedGbp)) >= 0.5;
  const compactGbp = (v: number) =>
    Math.abs(v) >= 1000 ? `£${(v / 1000).toFixed(1)}k` : `£${v.toFixed(0)}`;

  return (
    <div className="space-y-space-lg pb-16">
      {/* ─────────────────────────────────────────────────────────────
          TOP SECTION: CSV Ingestion Deck & Global Institutional KPI Bar
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* CSV Ingestion Deck (4 Cols) */}
        <div className="xl:col-span-4 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
              <span className="font-headline-md text-headline-md text-on-surface flex items-center gap-1.5 font-semibold">
                <span className="material-symbols-outlined text-[18px] text-primary">upload_file</span>
                CSV Ingestion Deck
              </span>
              <span className="font-label-caps text-label-caps px-space-xs py-0.5 rounded bg-surface-container text-outline">
                MAX 200MB
              </span>
            </div>

            {/* Dropzone Area */}
            <div
              {...getRootProps()}
              className={`border border-dashed rounded-lg p-space-md flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${isDragActive
                  ? 'border-primary bg-primary-container/10'
                  : 'border-outline-variant/60 hover:border-primary/60 bg-surface-container-lowest'
                }`}
            >
              <input {...getInputProps()} />
              <div className="w-9 h-9 rounded-full bg-surface-container-high flex items-center justify-center text-primary mb-2 shadow-inner">
                <span className="material-symbols-outlined text-[20px]">
                  {isUploading ? 'sync' : 'cloud_upload'}
                </span>
              </div>
              <span className="font-headline-md text-sm text-on-surface font-medium">
                {isUploading ? 'Parsing Statements...' : 'Drag & Drop Broker CSVs'}
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant my-1">
                Supports <code className="font-data-mono-sm text-primary">Trade*.csv</code> and{' '}
                <code className="font-data-mono-sm text-secondary">Transaction*.csv</code>
              </span>
              <div className="flex items-center gap-space-sm mt-1">
                <span className="font-label-caps text-[9px] text-on-surface-variant flex items-center gap-0.5">
                  <span className="material-symbols-outlined text-[12px] text-primary">verified</span>
                  AUTO-DETECT SCHEMA
                </span>
              </div>
            </div>

            {uploadError && (
              <div className="mt-2 text-error text-xs font-mono bg-error-container/20 p-2 rounded">
                {uploadError}
              </div>
            )}

            {isMissingTradeHistory && !uploadError && (
              <div className="mt-2 text-amber-400 text-xs font-mono bg-amber-500/10 border border-amber-500/30 p-2.5 rounded-lg flex items-start gap-2">
                <span className="material-symbols-outlined text-[16px] text-amber-400 mt-0.5 shrink-0">
                  warning
                </span>
                <div>
                  <span className="font-semibold block text-[11px]">Missing Trade History Statement</span>
                  <span className="text-[10px] text-on-surface-variant leading-tight block mt-0.5">
                    Transaction ledger uploaded, but position and valuation calculations require <code className="text-primary font-bold">Trade*.csv</code>. Please drop it here.
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Active File Status Bar */}
          <div className="pt-3 mt-3 border-t border-surface-container/40 text-on-surface-variant">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 truncate max-w-[240px]">
                <span
                  className={`material-symbols-outlined text-[15px] ${feed.state === 'loading' ? 'text-amber-400 animate-spin' : 'text-secondary'
                    }`}
                >
                  {feed.state === 'loading' ? 'sync' : 'description'}
                </span>
                <span className="font-data-mono-sm text-data-mono-sm text-secondary truncate" title={displayedFileName}>
                  {displayedFileName}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {feed.state === 'loading' ? (
                  <span className="font-label-caps text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold border border-amber-500/30 animate-pulse">
                    LOADING…
                  </span>
                ) : feed.state === 'offline' ? (
                  <span className="font-label-caps text-[9px] px-1.5 py-0.5 rounded bg-error-container/30 text-error font-semibold border border-error/40">
                    FEED_ERROR
                  </span>
                ) : isMissingTradeHistory ? (
                  <span className="font-label-caps text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold border border-amber-500/30">
                    MISSING TRADE HISTORY
                  </span>
                ) : (
                  <span className="font-label-caps text-label-caps text-outline">PARSER: IG</span>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setUploadedFiles([]);
                    onReset();
                  }}
                  title="Reset panels"
                  className="p-1 rounded hover:bg-surface-container text-outline hover:text-tertiary transition-colors"
                >
                  <span className="material-symbols-outlined text-[14px]">close</span>
                </button>
              </div>
            </div>

            {/* Gated on the samples themselves, not on feed.state: a healthy feed with no
                positions still puts SAMPLE_POSITIONS on screen, and that has to be disclosed. */}
            {isShowingSamples && (
              <span className="block mt-1.5 font-body-sm text-[10px] leading-tight text-amber-400">
                {feed.state === 'loading'
                  ? 'Showing sample data while prices load — these are not your figures yet.'
                  : 'Showing sample data — these are not your figures. Upload a TradeHistory*.csv to see your own portfolio.'}
              </span>
            )}
            {feed.state === 'offline' && (
              <span className="block mt-1.5 font-data-mono-sm text-[10px] leading-tight text-error">
                {feed.detail[0] ?? 'Cannot reach the backend.'}
              </span>
            )}
          </div>
        </div>

        {/* Global Institutional KPI Bar (8 Cols) */}
        <div className="xl:col-span-8 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between pb-space-xs border-b border-surface-container/40 mb-space-sm">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-secondary">account_balance_wallet</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Global Ledger Consolidated Telemetry
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-outline uppercase font-mono">
              BASE: GBP (£)
            </span>
          </div>

          {hasExcludedRows && (
            <div className="mb-space-sm text-xs font-mono bg-error-container/20 border border-error/40 p-2.5 rounded-lg flex items-start gap-2">
              <span className="material-symbols-outlined text-[16px] text-error mt-0.5 shrink-0">
                error
              </span>
              <div>
                <span className="font-semibold block text-[11px] text-error">
                  Figures below exclude {summary?.excluded_row_count} trade row
                  {summary?.excluded_row_count === 1 ? '' : 's'}
                </span>
                <span className="text-[10px] text-on-surface-variant leading-tight block mt-0.5">
                  {unresolvedSymbols.length} instrument name
                  {unresolvedSymbols.length === 1 ? '' : 's'} could not be resolved to a ticker, so
                  their cost basis and market value are omitted. Market value, invested cash and P&L
                  are all understated. Map them in{' '}
                  <span className="text-primary font-bold">Reference Data</span> to correct these
                  totals.
                </span>
                <span className="text-[10px] text-on-surface-variant block mt-1 truncate">
                  Unmapped: {unresolvedSymbols.map((s) => s.market_name).join(', ')}
                </span>
              </div>
            </div>
          )}

          {/* 4 Primary KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm py-space-xs">
            {/* Total Market Value */}
            <div className="p-space-sm rounded-lg bg-surface-container-lowest border border-surface-container/40 flex flex-col justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Total Market Value
              </span>
              <span className="font-data-mono-lg text-data-mono-lg text-on-surface tracking-tight my-1 font-semibold">
                £{totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-outline">
                <span className="material-symbols-outlined text-[14px]">
                  {isMissingTradeHistory ? 'warning' : 'info'}
                </span>
                <span>{isMissingTradeHistory ? 'Awaiting Trade History' : 'Day change unavailable'}</span>
              </div>
            </div>

            {/* Cash Available — IG's CSV exports carry no cash balance, so there is nothing to show */}
            <div className="p-space-sm rounded-lg bg-surface-container-lowest border border-surface-container/40 flex flex-col justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Cash Available (Uninvested)
              </span>
              <span
                className="font-data-mono-lg text-data-mono-lg text-outline tracking-tight my-1 font-semibold"
                title="No data source: cash balance is not present in IG trade or transaction statements"
              >
                —
              </span>
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-outline">
                <span className="material-symbols-outlined text-[14px]">info</span>
                <span>Not reported in CSV statements</span>
              </div>
            </div>

            {/* Total Cost Basis */}
            <div className="p-space-sm rounded-lg bg-surface-container-lowest border border-surface-container/40 flex flex-col justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Total Cost Basis
              </span>
              <span className="font-data-mono-lg text-data-mono-lg text-on-surface tracking-tight my-1 font-semibold">
                £{totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-outline">
                <span className="material-symbols-outlined text-[14px]">history</span>
                <span>{isMissingTradeHistory ? 'Awaiting Trade History' : 'Net deposits unavailable'}</span>
              </div>
            </div>

            {/* Total Unrealized P&L */}
            <div className="p-space-sm rounded-lg bg-surface-container-lowest border border-surface-container/40 flex flex-col justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Total Unrealized P&L
              </span>
              <span className={`font-data-mono-lg text-data-mono-lg tracking-tight my-1 font-semibold ${totalPnl >= 0 ? 'text-primary' : 'text-error'}`}>
                {totalPnl >= 0 ? '+' : ''}£{totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-primary">
                <span className="material-symbols-outlined text-[14px]">percent</span>
                <span>{isMissingTradeHistory ? '0.0% Portfolio ROI' : `+${pnlPercent}% Portfolio ROI`}</span>
              </div>
            </div>
          </div>

          {/* Currency Allocation Pill Strip */}
          <div className="mt-space-xs pt-space-xs border-t border-surface-container/30 flex flex-wrap items-center justify-between text-xs font-mono">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
              Currency Distribution:
            </span>
            {isMissingTradeHistory ? (
              <span className="text-outline text-xs italic">Awaiting Trade History statement to calculate currency exposure</span>
            ) : !hasAllocation ? (
              <span className="text-outline text-xs italic">
                {isShowingSamples ? 'Not calculated for sample data' : 'No priced holdings to allocate'}
              </span>
            ) : (
              <div className="flex items-center gap-space-md">
                {currencySlices.map((s) => (
                  <span
                    key={s.code}
                    className={`px-2 py-0.5 rounded bg-surface-container ${s.text} font-data-mono-sm`}
                  >
                    {s.code}: {allocationPct(s.gbp).toFixed(1)}% ({compactGbp(s.gbp)})
                  </span>
                ))}
                {hasUnclassified && (
                  <span className="px-2 py-0.5 rounded bg-surface-container text-outline font-data-mono-sm">
                    OTHER: {allocationPct(unclassifiedGbp).toFixed(1)}% ({compactGbp(unclassifiedGbp)})
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MIDDLE SECTION 1: Holdings Matrix (full width)
      ───────────────────────────────────────────────────────────── */}
      <div>
        {/* Comprehensive Holdings Table */}
        <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col">
          {/* Header & Search */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">format_list_bulleted</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Holdings & Valuation Ledger
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-label-caps text-[10px]">
                {filteredPositions.length} POSITIONS
              </span>
            </div>
            <div className="flex items-center gap-space-sm">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2 top-2 text-[15px] text-outline">
                  search
                </span>
                <input
                  type="text"
                  placeholder="Filter ticker or market..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-7 pr-3 py-1 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary w-48"
                />
              </div>
            </div>
          </div>

          {/* Table Container */}
          <div className="overflow-x-auto">
            {isMissingTradeHistory ? (
              <div className="py-16 px-4 flex flex-col items-center justify-center text-center bg-surface-container-lowest/50 rounded-lg border border-dashed border-outline-variant/40 my-3">
                <div className="w-12 h-12 rounded-full bg-amber-500/10 text-amber-400 flex items-center justify-center mb-3">
                  <span className="material-symbols-outlined text-2xl">table_rows</span>
                </div>
                <h3 className="font-headline-md text-base text-on-surface font-semibold mb-1">
                  Missing Trade History
                </h3>
                <p className="font-body-sm text-body-sm text-on-surface-variant max-w-md mb-4">
                  Open positions, current market prices, and unrealized P&L cannot be calculated from <code className="font-mono text-secondary">Transaction*.csv</code> alone.
                </p>
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-container text-xs font-mono text-outline border border-surface-container-high">
                  <span className="material-symbols-outlined text-[14px] text-primary">upload_file</span>
                  Please drop your <strong className="text-primary font-bold">TradeHistory*.csv</strong> file into the Ingestion Deck above.
                </div>
              </div>
            ) : (
              <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
                <thead>
                  <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                    <th className="py-2 px-space-sm">Ticker</th>
                    <th className="py-2 px-space-sm">Instrument Description</th>
                    <th className="py-2 px-space-sm text-right">Holdings</th>
                    <th className="py-2 px-space-sm text-right">Market Price</th>
                    <th className="py-2 px-space-sm text-right">Value (GBP)</th>
                    <th className="py-2 px-space-sm text-right">Net P&L (GBP)</th>
                    <th className="py-2 px-space-sm text-center">Trend (7D)</th>
                    <th className="py-2 px-space-sm text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container/40">
                  {filteredPositions.map((p, idx) => {
                    const isPositive = p.pnl_gbp >= 0;
                    const isSelected = p.ticker === selectedTicker;
                    return (
                      <tr
                        key={p.ticker + idx}
                        onClick={() => setSelectedTicker(p.ticker)}
                        className={`hover:bg-surface-container-high/60 cursor-pointer transition-colors ${isSelected ? 'bg-surface-container-high/90 shadow-[inset_2px_0_0_0_#4edea3]' : ''
                          }`}
                      >
                        <td className="py-2.5 px-space-sm font-semibold text-primary">
                          {p.ticker}
                        </td>
                        <td className="py-2.5 px-space-sm text-on-surface-variant truncate max-w-[180px]">
                          {p.market}
                        </td>
                        <td className="py-2.5 px-space-sm text-right text-on-surface">
                          {p.quantity.toLocaleString()}
                        </td>
                        <td className="py-2.5 px-space-sm text-right text-on-surface-variant">
                          {p.currency === 'USD' ? '$' : p.currency === 'EUR' ? '€' : '£'}
                          {(p.current_price || 0).toFixed(2)}
                        </td>
                        <td className="py-2.5 px-space-sm text-right text-on-surface font-medium">
                          £{p.market_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td className="py-2.5 px-space-sm text-right">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${isPositive
                                ? 'bg-primary/10 text-primary border border-primary/20'
                                : 'bg-error/10 text-error border border-error/20'
                              }`}
                          >
                            {isPositive ? '+' : ''}£{p.pnl_gbp.toFixed(2)}
                          </span>
                        </td>
                        <td
                          className="py-2.5 px-space-sm text-center text-outline"
                          title="No data source: 7-day price history is not loaded for the ledger"
                        >
                          —
                        </td>
                        <td className="py-2.5 px-space-sm text-center">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTicker(p.ticker);
                            }}
                            className="px-2 py-0.5 rounded bg-surface-container hover:bg-surface-container-highest text-secondary text-[10px] font-label-caps transition-colors"
                          >
                            INSPECT
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          FLOATING WINDOW: Single Instrument Inspector (opens from the ledger)
      ───────────────────────────────────────────────────────────── */}
      {selectedHolding && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setSelectedTicker(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Single Instrument Inspector & Execution Blotter"
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-6xl max-h-[90vh] overflow-y-auto bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-2xl"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-space-sm border-b border-surface-container/40 mb-space-sm">
              <div className="flex items-center gap-space-sm">
                <button
                  type="button"
                  onClick={() => setSelectedTicker(null)}
                  title="Close (Esc)"
                  aria-label="Close inspector"
                  className="w-7 h-7 flex items-center justify-center rounded bg-surface-container hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
                <span className="material-symbols-outlined text-[20px] text-primary">insights</span>
                <div>
                  <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                    Single Instrument Inspector & Execution Blotter
                  </span>
                  <div className="font-label-caps text-[10px] text-outline">
                    FOCUSED INSTRUMENT: {selectedHolding.ticker} • {selectedHolding.market}
                  </div>
                </div>
              </div>

              {/* Instrument Dropdown Selector */}
              <div className="flex items-center gap-space-sm">
                <span className="font-label-caps text-label-caps text-on-surface-variant">SWITCH TICKER:</span>
                <select
                  value={selectedHolding.ticker}
                  onChange={(e) => setSelectedTicker(e.target.value)}
                  className="px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-primary font-bold focus:outline-none focus:border-primary"
                >
                  {positions.map((p) => (
                    <option key={p.ticker} value={p.ticker}>
                      {p.ticker} — {p.market}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Quick Inspector Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm mb-space-md">
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">CURRENT POSITION</span>
                <span className="font-data-mono-lg text-sm text-on-surface font-semibold">
                  {selectedHolding.quantity.toLocaleString()} Shares
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">
                  AVG EXECUTION BASIS {avgExecutionBasis && '(GBP/SHARE)'}
                </span>
                <span
                  className={`font-data-mono-lg text-sm font-semibold ${avgExecutionBasis ? 'text-on-surface' : 'text-outline'}`}
                  title={
                    avgExecutionBasis
                      ? 'Total settled value of recorded buys divided by the quantity bought'
                      : 'No data source: no settled buy values recorded for this instrument'
                  }
                >
                  {avgExecutionBasis ?? '—'}
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">CURRENT VALUE (GBP)</span>
                <span className="font-data-mono-lg text-sm text-on-surface font-semibold">
                  £{selectedHolding.market_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">NET UNREALIZED P&L</span>
                <span className={`font-data-mono-lg text-sm font-semibold ${selectedHolding.pnl_gbp >= 0 ? 'text-primary' : 'text-error'}`}>
                  {selectedHolding.pnl_gbp >= 0 ? '+' : ''}£{selectedHolding.pnl_gbp.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Inspector Chart & Execution History */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
              {/* SVG Price Chart with Execution Markers (8 cols) */}
              <div className="lg:col-span-8 bg-surface-container-lowest p-space-sm rounded-lg border border-surface-container/40">
                <div className="flex items-center justify-between px-2 py-1 mb-2 text-xs font-mono text-outline border-b border-surface-container/20">
                  <span className="text-on-surface font-semibold">PRICE TRAJECTORY & EXECUTION FLAGS</span>
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1 text-primary">
                      <span className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-b-[6px] border-b-primary" />
                      BUY FILLS
                    </span>
                    <span className="flex items-center gap-1 text-tertiary">
                      <span className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-t-[6px] border-t-tertiary" />
                      SELL FILLS
                    </span>
                  </div>
                </div>

                <PriceTradeChart ticker={selectedHolding.ticker} trades={chartTrades} />
              </div>

              {/* Single Instrument Trade Fills (4 cols) */}
              <div className="lg:col-span-4 bg-surface-container-lowest p-space-sm rounded-lg border border-surface-container/40 flex flex-col justify-between">
                <div>
                  <span className="font-label-caps text-label-caps text-outline block mb-2 uppercase">
                    {selectedHolding.ticker} Execution Audit
                  </span>
                  <div className="space-y-2 max-h-[260px] overflow-y-auto pr-1">
                    {inspectorTrades.length === 0 ? (
                      <div className="p-3 text-center text-outline font-mono text-xs">
                        No executions recorded for this instrument.
                      </div>
                    ) : (
                      inspectorTrades.map((t, i) => {
                        const isBuy = t.activity !== 'SELL';
                        return (
                          <div
                            key={`${t.date}-${t.time}-${i}`}
                            className="p-2 rounded bg-surface-container-low border border-surface-container/30 flex items-center justify-between text-xs font-mono"
                          >
                            <div>
                              <span className={`${isBuy ? 'text-primary' : 'text-tertiary'} font-bold`}>
                                {isBuy ? 'BUY' : 'SELL'} {t.qty.toLocaleString()} shs
                              </span>
                              <span className="text-outline block text-[10px]">
                                {t.date} {t.time}
                              </span>
                            </div>
                            <div className="text-right">
                              <span className="text-on-surface font-semibold">{t.fill}</span>
                              {t.value && (
                                <span className="text-outline block text-[10px]">
                                  {isBuy ? 'Settled' : 'Proceeds'}: {t.value}
                                </span>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>

                <div className="pt-2 mt-2 border-t border-surface-container/30 flex items-center justify-between text-[11px] font-mono text-outline">
                  <span>BROKER: IG BROKERAGE</span>
                  <span className="text-secondary">{inspectorTrades.length} EXECUTIONS</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MIDDLE SECTION 3: Trade Activities & Currency Allocation
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Trade Activities (8 Cols) */}
        <div className="xl:col-span-8 min-w-0 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-secondary">history</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold whitespace-nowrap">
                Trade Activities
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-space-sm">
              {/* Instrument filter with autocomplete */}
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2 top-1.5 text-[15px] text-outline">
                  search
                </span>
                <input
                  type="text"
                  role="combobox"
                  aria-expanded={showInstrumentSuggestions && instrumentSuggestions.length > 0}
                  aria-autocomplete="list"
                  placeholder="Instrument, symbol or company..."
                  value={instrumentQuery}
                  onChange={(e) => {
                    setInstrumentQuery(e.target.value);
                    setSelectedInstrumentKey(null);
                    setShowInstrumentSuggestions(true);
                    setHighlightedSuggestion(-1);
                  }}
                  onFocus={() => setShowInstrumentSuggestions(true)}
                  onBlur={() => setShowInstrumentSuggestions(false)}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                      e.preventDefault();
                      setShowInstrumentSuggestions(true);
                      setHighlightedSuggestion((i) => Math.min(i + 1, instrumentSuggestions.length - 1));
                    } else if (e.key === 'ArrowUp') {
                      e.preventDefault();
                      setHighlightedSuggestion((i) => Math.max(i - 1, 0));
                    } else if (e.key === 'Enter' && showInstrumentSuggestions && highlightedSuggestion >= 0) {
                      e.preventDefault();
                      selectInstrument(instrumentSuggestions[highlightedSuggestion]);
                    } else if (e.key === 'Escape') {
                      setShowInstrumentSuggestions(false);
                    }
                  }}
                  className="pl-7 pr-7 py-1 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary w-60"
                />
                {instrumentQuery && (
                  <button
                    type="button"
                    onClick={() => selectInstrument(null)}
                    title="Clear instrument filter"
                    className="absolute right-1.5 top-1 p-0.5 rounded text-outline hover:text-on-surface"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                )}
                {showInstrumentSuggestions && instrumentSuggestions.length > 0 && (
                  <ul
                    role="listbox"
                    className="absolute z-20 mt-1 w-full max-h-60 overflow-y-auto rounded border border-surface-container-high bg-surface-container-lowest shadow-lg text-xs font-mono"
                  >
                    {instrumentSuggestions.map((o, i) => (
                      <li
                        key={o.key}
                        role="option"
                        aria-selected={i === highlightedSuggestion}
                        title={o.variants.join('\n')}
                        // mousedown fires before the input's blur, so the click isn't lost
                        onMouseDown={(e) => {
                          e.preventDefault();
                          selectInstrument(o);
                        }}
                        onMouseEnter={() => setHighlightedSuggestion(i)}
                        className={`px-2 py-1.5 cursor-pointer flex items-center justify-between gap-2 ${i === highlightedSuggestion ? 'bg-surface-container-high' : ''
                          }`}
                      >
                        <span className="text-on-surface truncate">
                          {o.label}
                          {o.variants.length > 1 && (
                            <span className="ml-1 text-[10px] text-outline">×{o.variants.length} sessions</span>
                          )}
                        </span>
                        {o.ticker && <span className="text-primary font-semibold shrink-0">{o.ticker}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Period Pills */}
              <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
                {(
                  [
                    ['QUARTER', quarterLabel],
                    ['YEAR', 'CURRENT YEAR'],
                    ['ALL', 'ALL'],
                  ] as [ActivityPeriod, string][]
                ).map(([period, label]) => (
                  <button
                    key={period}
                    type="button"
                    onClick={() => setActivityPeriod(period)}
                    className={`px-2.5 py-1 rounded transition-colors ${activityPeriod === period
                        ? 'bg-surface-container-high text-primary font-bold'
                        : 'text-outline hover:text-on-surface'
                      }`}
                  >
                    {label} ({instrumentActivities.filter((a) => inPeriod(a, period)).length})
                  </button>
                ))}
              </div>

              {/* Side Pills (click again to clear) */}
              <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
                <button
                  type="button"
                  onClick={() => setActivitySide((s) => (s === 'BUY' ? 'ALL' : 'BUY'))}
                  className={`px-2.5 py-1 rounded transition-colors ${activitySide === 'BUY'
                      ? 'bg-surface-container-high text-primary font-bold'
                      : 'text-outline hover:text-on-surface'
                    }`}
                >
                  BUY ({periodActivities.filter((a) => a.activity === 'BUY').length})
                </button>
                <button
                  type="button"
                  onClick={() => setActivitySide((s) => (s === 'SELL' ? 'ALL' : 'SELL'))}
                  className={`px-2.5 py-1 rounded transition-colors ${activitySide === 'SELL'
                      ? 'bg-surface-container-high text-tertiary font-bold'
                      : 'text-outline hover:text-on-surface'
                    }`}
                >
                  SELL ({periodActivities.filter((a) => a.activity === 'SELL').length})
                </button>
              </div>
            </div>
          </div>

          {/* Activity Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
              <thead>
                <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                  <th className="py-2 px-space-sm">Activity</th>
                  <th className="py-2 px-space-sm">Market Instrument</th>
                  <th className="py-2 px-space-sm text-right">Qty</th>
                  <th className="py-2 px-space-sm text-right">Fill Price</th>
                  <th className="py-2 px-space-sm text-right">Settled Value (GBP)</th>
                  <th className="py-2 px-space-sm">Date</th>
                  <th className="py-2 px-space-sm">Time (UTC)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container/30">
                {filteredActivity.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-on-surface-variant font-mono text-xs">
                      {isMissingTradeHistory
                        ? 'No trade activity available (Missing Trade History statement).'
                        : activityPeriod !== 'ALL' && instrumentActivities.length > 0
                          ? `No matching trades in ${activityPeriod === 'QUARTER' ? quarterLabel : 'the current year'} — try a wider period.`
                          : 'No activity matches the current filter.'}
                    </td>
                  </tr>
                ) : (
                  filteredActivity.map((act, idx) => (
                    <tr key={idx} className="hover:bg-surface-container-high/40">
                      <td className="py-2 px-space-sm">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${act.activity === 'BUY'
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'bg-error/10 text-error border border-error/20'
                            }`}
                        >
                          {act.activity}
                        </span>
                      </td>
                      <td className="py-2 px-space-sm text-on-surface font-medium">
                        {act.market}
                        {activityTicker(act) && (
                          <span className="ml-1.5 text-[10px] text-primary">{activityTicker(act)}</span>
                        )}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface">
                        {act.qty}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface-variant">
                        {act.fill}
                      </td>
                      <td className="py-2 px-space-sm text-right font-semibold text-on-surface">
                        {act.value}
                      </td>
                      <td className="py-2 px-space-sm text-outline">
                        {act.date}
                      </td>
                      <td className="py-2 px-space-sm text-outline">
                        {act.time}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Currency Allocation (4 Cols) */}
        <div className="xl:col-span-4 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
              <span className="font-headline-md text-headline-md text-on-surface font-semibold flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[18px] text-secondary">donut_large</span>
                Currency Allocation
              </span>
              <span className="font-label-caps text-label-caps text-outline">SPOT FX</span>
            </div>

            {/* SVG Donut Chart */}
            <div className="flex items-center justify-center py-4">
              {isMissingTradeHistory || !hasAllocation ? (
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
                    {currencySlices.map((s, i) => {
                      const offset = currencySlices
                        .slice(0, i)
                        .reduce((acc, prev) => acc + allocationPct(prev.gbp), 0);
                      return (
                        <path
                          key={s.code}
                          className={s.text}
                          strokeDasharray={`${allocationPct(s.gbp).toFixed(2)}, 100`}
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
                      {compactGbp(allocationTotal)}
                    </span>
                    <span className="font-label-caps text-[9px] text-outline uppercase">
                      {classifiedPct.toFixed(0)}% Allocated
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Currency Breakdown Legend */}
            {isMissingTradeHistory || !hasAllocation ? (
              <div className="p-3 text-center text-outline font-mono text-xs bg-surface-container-lowest rounded border border-surface-container/30">
                {isMissingTradeHistory ? 'Awaiting TradeHistory*.csv' : 'No currency breakdown available'}
              </div>
            ) : (
              <div className="space-y-2 mt-2">
                {currencySlices.map((s) => (
                  <div
                    key={s.code}
                    className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30"
                  >
                    <div className="flex items-center gap-2">
                      <div className={`w-2.5 h-2.5 rounded-full ${s.dot}`} />
                      <span className="font-body-sm text-xs text-on-surface font-medium">{s.label}</span>
                    </div>
                    <span className="font-data-mono-sm text-xs text-on-surface">
                      {allocationPct(s.gbp).toFixed(1)}% • {compactGbp(s.gbp)}
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
                      {allocationPct(unclassifiedGbp).toFixed(1)}% • {compactGbp(unclassifiedGbp)}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="mt-4 pt-3 border-t border-surface-container/40 text-[11px] text-outline font-mono flex items-center justify-between">
            <span title="No data source: hedging is not reported in IG CSV statements">RISK HEDGE: —</span>
            <span title="No data source: liquidity locks are not reported in IG CSV statements">
              LIQUIDITY LOCK: —
            </span>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BOTTOM SECTION: Cashflow Waterfall Breakdown
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[18px] text-tertiary-fixed">waterfall_chart</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Cashflow Waterfall & Fee Telemetry
            </span>
          </div>
          <span className="font-label-caps text-label-caps text-outline uppercase font-mono">
            INCEPTION-TO-DATE AUDIT
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-space-sm">
          {[
            'DIVIDENDS RECEIVED',
            'CASH INTEREST',
            'DEALING COMMISSIONS',
            'STAMP DUTY (SDRT)',
            'NET CASH REINVESTED',
          ].map((label) => (
            <div key={label} className="p-3 rounded bg-surface-container-lowest border border-surface-container/30">
              <span className="font-label-caps text-[10px] text-outline block">{label}</span>
              <span
                className="font-data-mono-lg text-sm text-outline font-bold block mt-1"
                title="No data source: cashflow categories are not yet read from the transaction statement"
              >
                —
              </span>
              <span className="font-body-sm text-[10px] text-on-surface-variant">Not yet calculated</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
