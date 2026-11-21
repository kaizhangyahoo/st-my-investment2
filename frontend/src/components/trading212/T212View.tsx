import React, { useState, useEffect, useMemo } from 'react';
import { t212Api } from '../../services/api';
import { T212AccountSummary, T212Position, T212Order, T212Dividend, T212Page } from '../../types';
import { PriceTradeChart, ChartTrade } from '../dashboard/PriceTradeChart';

// Institutional fallback data matching Stitch screen
const SAMPLE_T212_POSITIONS: T212Position[] = [
  { ticker: 'TRI', name: 'Thomson Reuters Corp', isin: 'CA8849037095', currency: 'USD', quantity: 65, avg_price_paid: 154.20, current_price: 168.40, total_cost_gbp: 7748.00, current_value_gbp: 8462.10, unrealized_pnl_gbp: 714.10, fx_impact_gbp: -42.10 },
  { ticker: 'EQQQ.L', name: 'iShares NASDAQ 100 Acc', isin: 'IE0032077012', currency: 'GBP', quantity: 24, avg_price_paid: 395.10, current_price: 432.80, total_cost_gbp: 9482.40, current_value_gbp: 10387.20, unrealized_pnl_gbp: 904.80, fx_impact_gbp: 0.00 },
  { ticker: 'LITE', name: 'Lumentum Holdings Inc', isin: 'US55024U1097', currency: 'USD', quantity: 380, avg_price_paid: 48.60, current_price: 54.30, total_cost_gbp: 14275.10, current_value_gbp: 15948.30, unrealized_pnl_gbp: 1673.20, fx_impact_gbp: -85.20 },
  { ticker: 'GOOG', name: 'Alphabet Inc Class C', isin: 'US02079K1079', currency: 'USD', quantity: 45, avg_price_paid: 162.10, current_price: 178.50, total_cost_gbp: 5637.20, current_value_gbp: 6207.40, unrealized_pnl_gbp: 570.20, fx_impact_gbp: -31.40 },
  { ticker: 'AMZN', name: 'Amazon.com Inc', isin: 'US0231351067', currency: 'USD', quantity: 50, avg_price_paid: 178.40, current_price: 194.20, total_cost_gbp: 6893.30, current_value_gbp: 7503.80, unrealized_pnl_gbp: 610.50, fx_impact_gbp: -39.10 },
  { ticker: 'WCOP.L', name: 'WisdomTree Copper', isin: 'GB00B15KXQ89', currency: 'GBP', quantity: 450, avg_price_paid: 28.10, current_price: 31.40, total_cost_gbp: 12645.00, current_value_gbp: 14130.00, unrealized_pnl_gbp: 1485.00, fx_impact_gbp: 0.00 },
  { ticker: 'OKLO', name: 'Oklo Inc', isin: 'US6708681027', currency: 'USD', quantity: 180, avg_price_paid: 18.40, current_price: 24.10, total_cost_gbp: 2560.10, current_value_gbp: 3352.40, unrealized_pnl_gbp: 792.30, fx_impact_gbp: -18.20 },
];

type OrderPeriod = 'QUARTER' | 'YEAR' | 'ALL';

const CURRENCY_PREFIX: Record<string, string> = { GBP: '£', USD: '$', EUR: '€' };

// GBX is pence and takes a trailing `p`, which matters: the account's largest holding is quoted
// in it, and a leading symbol would read as a different currency a hundred times the size.
const money = (value: number, currency?: string | null, digits = 2) => {
  const amount = value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  const code = currency || '';
  if (CURRENCY_PREFIX[code]) return `${CURRENCY_PREFIX[code]}${amount}`;
  if (code === 'GBX') return `${amount}p`;
  return code ? `${amount} ${code}` : amount;
};

// Donut slice colours, in the order currencies are ranked by value.
// The sign belongs outside the symbol, and a four-figure loss needs its separator: this account's
// unrealised P&L was rendering as `£-13948.29`.
const signedGbp = (value: number) => `${value < 0 ? '-' : '+'}${money(Math.abs(value), 'GBP')}`;

const EXPOSURE_COLOURS = ['#4edea3', '#93ccff', '#f5c77e', '#d8a0ff', '#ff9b9b'];

const isoDate = (raw: string | null) => (raw ? raw.slice(0, 10) : null);

const stamp = (raw: string | null) => (raw ? raw.replace('T', ' ').slice(0, 19) : '—');

export const T212View: React.FC = () => {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('t212_api_key') || '');
  const [apiSecret, setApiSecret] = useState(() => localStorage.getItem('t212_api_secret') || '');
  const [showSecret, setShowSecret] = useState(false);
  const [summary, setSummary] = useState<T212AccountSummary | null>(null);
  const [positions, setPositions] = useState<T212Position[]>([]);
  const [orders, setOrders] = useState<T212Page<T212Order> | null>(null);
  const [dividends, setDividends] = useState<T212Page<T212Dividend> | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [inspectedTicker, setInspectedTicker] = useState<string | null>(null);

  const [orderPeriod, setOrderPeriod] = useState<OrderPeriod>('ALL');
  const [orderSide, setOrderSide] = useState<'BUY' | 'SELL' | 'ALL'>('ALL');
  const [instrumentQuery, setInstrumentQuery] = useState('');
  const [selectedInstrumentKey, setSelectedInstrumentKey] = useState<string | null>(null);
  const [showInstrumentSuggestions, setShowInstrumentSuggestions] = useState(false);
  const [highlightedSuggestion, setHighlightedSuggestion] = useState(-1);

  const fetchT212Data = async () => {
    setLoading(true);
    setSyncStatus(null);
    const failed: string[] = [];
    let overviewSuccess = false;
    let positionsSuccess = false;

    // Sequential with gaps throughout: the account summary is 1 req/5s, positions 1 req/1s and
    // the two history endpoints share 6 req/min, so a parallel fan-out just earns a 429.
    const step = async <T,>(label: string, call: () => Promise<T>): Promise<T | null> => {
      try {
        return await call();
      } catch (err: any) {
        failed.push(`${label}: ${err.response?.data?.detail || err.message}`);
        return null;
      }
    };

    try {
      const sumRes = await step('Overview', () =>
        t212Api.getOverview(apiKey || undefined, apiSecret || undefined)
      );
      if (sumRes) {
        setSummary(sumRes);
        overviewSuccess = true;
      }

      await new Promise((r) => setTimeout(r, 650));

      const posRes = await step('Positions', () =>
        t212Api.getPositions(apiKey || undefined, apiSecret || undefined)
      );
      if (Array.isArray(posRes)) {
        setPositions(posRes);
        positionsSuccess = true;
      }

      // Only worth asking for history once the credentials have proved themselves, so a bad key
      // does not spend the 6/min history budget on calls that will all fail the same way.
      if (overviewSuccess || positionsSuccess) {
        await new Promise((r) => setTimeout(r, 650));
        const ordRes = await step('Orders', () =>
          t212Api.getOrders(apiKey || undefined, apiSecret || undefined)
        );
        if (ordRes?.items) setOrders(ordRes);

        await new Promise((r) => setTimeout(r, 650));
        const divRes = await step('Dividends', () =>
          t212Api.getDividends(apiKey || undefined, apiSecret || undefined)
        );
        if (divRes?.items) setDividends(divRes);
      }

      const notice = failed.join(' ');
      if (overviewSuccess && positionsSuccess && !notice) {
        setSyncStatus('API SYNC SUCCESSFUL (LIVE FEED)');
      } else if (overviewSuccess || positionsSuccess) {
        setSyncStatus(`PARTIAL SYNC — ${notice}`);
      } else if (apiKey) {
        setSyncStatus(`API SYNC FAILED: ${notice}`);
      } else {
        setSyncStatus('SAMPLE DATA LOADED (ENTER API KEY TO SYNC LIVE)');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchT212Data();
  }, []);

  const handleSaveKeys = () => {
    localStorage.setItem('t212_api_key', apiKey);
    localStorage.setItem('t212_api_secret', apiSecret);
    fetchT212Data();
  };

  const hasLiveSummary = summary !== null;
  const hasLivePositions = positions.length > 0;
  const displayPositions = hasLivePositions ? positions : SAMPLE_T212_POSITIONS;

  const totalValue = hasLiveSummary ? summary.total_value : 84210.50;
  const cashAvailable = hasLiveSummary ? summary.cash_available : 4820.10;
  const investmentsValue = hasLiveSummary ? summary.investments_value : 79390.40;
  const totalCost = hasLiveSummary ? summary.total_cost : 71200.00;
  const realisedPnl = hasLiveSummary ? summary.realized_pnl : 2140.80;
  const unrealisedPnl = hasLiveSummary ? summary.unrealized_pnl : 8190.40;
  const fxImpact = hasLiveSummary
    ? (positions.reduce((acc, p) => acc + (p.fx_impact_gbp || 0), 0) || 0.0)
    : -420.50;

  /* ── Currency exposure, derived from whichever position set is on screen ───────────── */

  const exposure = useMemo(() => {
    const byCurrency = new Map<string, number>();
    displayPositions.forEach((p) => {
      const key = p.currency || 'GBP';
      byCurrency.set(key, (byCurrency.get(key) || 0) + (p.current_value_gbp || 0));
    });
    const total = Array.from(byCurrency.values()).reduce((a, b) => a + b, 0);
    const slices = Array.from(byCurrency.entries())
      .map(([currency, value]) => ({
        currency,
        value,
        share: total > 0 ? (value / total) * 100 : 0,
      }))
      .sort((a, b) => b.value - a.value);
    const foreign = slices.filter((s) => s.currency !== 'GBP').reduce((a, s) => a + s.value, 0);
    return { slices, total, foreign };
  }, [displayPositions]);

  const CIRCUMFERENCE = 2 * Math.PI * 38;

  /* ── Order history filters, mirroring the IG ledger's instrument + period controls ─── */

  const orderItems = orders?.items ?? [];

  const instrumentOptions = useMemo(() => {
    const groups = new Map<string, { key: string; label: string; ticker: string }>();
    orderItems.forEach((o) => {
      if (!groups.has(o.ticker)) {
        groups.set(o.ticker, { key: o.ticker, label: o.name, ticker: o.symbol || o.ticker });
      }
    });
    return Array.from(groups.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [orderItems]);

  const normalizedQuery = instrumentQuery.trim().toLowerCase();
  const instrumentSuggestions = selectedInstrumentKey
    ? instrumentOptions
    : instrumentOptions.filter(
        (g) =>
          !normalizedQuery ||
          g.ticker.toLowerCase().includes(normalizedQuery) ||
          g.label.toLowerCase().includes(normalizedQuery) ||
          g.key.toLowerCase().includes(normalizedQuery)
      );
  const matchingKeys = new Set(instrumentSuggestions.map((g) => g.key));

  const selectInstrument = (group: { key: string; label: string; ticker: string } | null) => {
    setInstrumentQuery(group ? `${group.label} (${group.ticker})` : '');
    setSelectedInstrumentKey(group ? group.key : null);
    setShowInstrumentSuggestions(false);
    setHighlightedSuggestion(-1);
  };

  const now = new Date();
  const quarterIndex = Math.floor(now.getMonth() / 3);
  const quarterLabel = `Q${quarterIndex + 1} ${now.getFullYear()}`;
  const periodStart: Record<OrderPeriod, Date | null> = {
    QUARTER: new Date(now.getFullYear(), quarterIndex * 3, 1),
    YEAR: new Date(now.getFullYear(), 0, 1),
    ALL: null,
  };
  const inPeriod = (order: T212Order, period: OrderPeriod) => {
    const start = periodStart[period];
    if (!start) return true;
    if (!order.created_at) return false;
    return new Date(order.created_at) >= start;
  };

  const instrumentOrders = orderItems.filter((o) =>
    selectedInstrumentKey
      ? o.ticker === selectedInstrumentKey
      : !normalizedQuery || matchingKeys.has(o.ticker)
  );
  const periodOrders = instrumentOrders.filter((o) => inPeriod(o, orderPeriod));
  const filteredOrders = periodOrders.filter((o) => orderSide === 'ALL' || o.side === orderSide);

  /* ── Instrument inspector ──────────────────────────────────────────────────────────── */

  const inspected = inspectedTicker
    ? displayPositions.find((p) => p.ticker === inspectedTicker) || null
    : null;

  // Only filled orders can be plotted: a rejected order has no execution price to mark.
  const inspectedFills = inspected
    ? orderItems
        .filter((o) => o.ticker === inspected.ticker && o.fill_price !== null)
        .sort((a, b) => (b.filled_at || '').localeCompare(a.filled_at || ''))
    : [];
  // Keyed on the fill, not the order: tranches of one order can share a price and a timestamp.
  const inspectedFillsKey = inspectedFills.map((o) => o.fill_id || o.id).join(';');

  // One marker per date and side, not per fill. A single order here filled as 23 tranches on one
  // day, which plotted individually overprint into an illegible smear of labels at one x position.
  // The marker sits at the volume-weighted price actually paid across that day's tranches.
  const chartTrades = useMemo<ChartTrade[]>(() => {
    const groups = new Map<string, { date: string; side: 'BUY' | 'SELL'; qty: number; notional: number }>();
    inspectedFills.forEach((o) => {
      const date = isoDate(o.filled_at) || isoDate(o.created_at) || '';
      const side: 'BUY' | 'SELL' = o.side === 'SELL' ? 'SELL' : 'BUY';
      // Sell quantities arrive negative; the side already carries the direction.
      const qty = Math.abs(o.filled_quantity ?? 0);
      const group = groups.get(`${date}|${side}`) || { date, side, qty: 0, notional: 0 };
      group.qty += qty;
      group.notional += qty * (o.fill_price ?? 0);
      groups.set(`${date}|${side}`, group);
    });
    return Array.from(groups.values()).map((g) => ({
      date: g.date,
      side: g.side,
      qty: Number(g.qty.toFixed(4)),
      price: g.qty > 0 ? g.notional / g.qty : null,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspectedFillsKey]);

  useEffect(() => {
    if (!inspected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setInspectedTicker(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [inspected]);

  /* ── Dividend totals ───────────────────────────────────────────────────────────────── */

  const dividendItems = dividends?.items ?? [];
  const dividendTotals = useMemo(() => {
    const byCurrency = new Map<string, number>();
    dividendItems.forEach((d) => {
      byCurrency.set(d.currency, (byCurrency.get(d.currency) || 0) + d.amount);
    });
    return Array.from(byCurrency.entries());
  }, [dividendItems]);

  return (
    <div className="space-y-space-lg pb-16">
      {/* ─────────────────────────────────────────────────────────────
          1. API AUTHENTICATION & SYNC TELEMETRY BAR
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[20px] text-primary">key</span>
            <div>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Trading 212 REST API Gateway
              </span>
              <span className="font-label-caps text-[10px] text-outline block">
                DIRECT SECURE HEADERS (x-t212-key • x-t212-secret)
              </span>
            </div>
          </div>

          {/* Credentials Inputs. Both masked by one toggle: the key authenticates just as much as
              the secret does, so leaving it in clear text only exposed it to screen-shares. */}
          <div className="flex flex-wrap items-center gap-space-sm flex-1 max-w-2xl">
            <input
              type={showSecret ? 'text' : 'password'}
              placeholder="Enter Trading 212 API Key..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="flex-1 min-w-[160px] px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary"
            />
            <div className="relative flex-1 min-w-[160px]">
              <input
                type={showSecret ? 'text' : 'password'}
                placeholder="Enter API Secret..."
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                className="w-full px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary pr-8"
              />
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                title={showSecret ? 'Hide credentials' : 'Show credentials'}
                className="absolute right-2 top-2 text-outline hover:text-on-surface"
              >
                <span className="material-symbols-outlined text-[14px]">
                  {showSecret ? 'visibility_off' : 'visibility'}
                </span>
              </button>
            </div>
            <button
              type="button"
              onClick={handleSaveKeys}
              disabled={loading}
              className="px-3 py-1.5 rounded bg-primary-container hover:bg-primary font-bold text-on-primary-container text-xs font-mono transition-colors flex items-center gap-1 shadow-sm"
            >
              <span className="material-symbols-outlined text-[15px]">
                {loading ? 'sync' : 'bolt'}
              </span>
              <span>{loading ? 'SYNCING...' : 'SYNC API'}</span>
            </button>
          </div>
        </div>

        {syncStatus && (
          <div className="mt-3 pt-2 border-t border-surface-container/30 flex items-center justify-between font-label-caps text-[10px]">
            <span className={`${hasLiveSummary ? 'text-primary' : 'text-secondary'} flex items-center gap-1`}>
              <span className={`w-1.5 h-1.5 rounded-full ${hasLiveSummary ? 'bg-primary' : 'bg-secondary'} animate-pulse`} />
              {syncStatus}
            </span>
            <span className="text-outline">T212 PORTFOLIO VIEW</span>
          </div>
        )}
      </div>

      {/* ─────────────────────────────────────────────────────────────
          2. TELEMETRY CARDS METRICS BAR (Bloomberg Dense Grid)
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-space-sm">
        {/* Total Value */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Total Value</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            £{totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">
            {hasLiveSummary ? `ACC #${summary?.id}` : 'ACCOUNT #177300'}
          </span>
        </div>

        {/* Cash Available */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Cash Available</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            £{cashAvailable.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-secondary">Free Capital</span>
        </div>

        {/* Investments */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Investments</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            £{investmentsValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">
            {hasLivePositions ? `${positions.length} Live Holdings` : `${displayPositions.length} Holdings`}
          </span>
        </div>

        {/* Cost Basis */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Cost Basis</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            £{totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">Net Capital In</span>
        </div>

        {/* Realised P&L */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Realised P&L</span>
          <span className={`font-data-mono-lg text-sm font-bold my-1 ${realisedPnl >= 0 ? 'text-primary' : 'text-error'}`}>
            {signedGbp(realisedPnl)}
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">Closed Fills</span>
        </div>

        {/* FX Impact */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">FX Impact</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            {signedGbp(fxImpact)}
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">FX Drift</span>
        </div>

        {/* Unrealised P&L */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Unrealised P&L</span>
          <span className={`font-data-mono-lg text-sm font-bold my-1 ${unrealisedPnl >= 0 ? 'text-primary' : 'text-error'}`}>
            {signedGbp(unrealisedPnl)}
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">
            {totalCost > 0 ? `${((unrealisedPnl / totalCost) * 100).toFixed(1)}% Return` : 'No cost basis'}
          </span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          3. OPEN POSITIONS & CURRENCY EXPOSURE
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Open Positions Table (8 Cols) */}
        <div className="xl:col-span-8 min-w-0 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
          <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">show_chart</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                T212 Open positions
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-caps text-[10px]">
                {hasLivePositions ? `${positions.length} LIVE` : 'SAMPLE'}
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-outline uppercase font-mono">
              CLICK A ROW TO INSPECT
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
              <thead>
                <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                  <th className="py-2 px-space-sm">Instrument</th>
                  <th className="py-2 px-space-sm text-right">Qty</th>
                  <th className="py-2 px-space-sm text-right">Avg Buy</th>
                  <th className="py-2 px-space-sm text-right">Current</th>
                  <th className="py-2 px-space-sm text-right">Value (GBP)</th>
                  <th className="py-2 px-space-sm text-right">% Port</th>
                  <th className="py-2 px-space-sm text-right">Unrealised</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container/30">
                {displayPositions.map((pos) => {
                  const portPercent = totalValue > 0 ? ((pos.current_value_gbp / totalValue) * 100).toFixed(1) : '0.0';
                  const isPositive = pos.unrealized_pnl_gbp >= 0;
                  return (
                    <tr
                      key={pos.ticker}
                      onClick={() => setInspectedTicker(pos.ticker)}
                      title={`Inspect ${pos.name}`}
                      className="hover:bg-surface-container-high/50 cursor-pointer transition-colors"
                    >
                      <td className="py-2 px-space-sm">
                        <span className="font-bold text-primary block">{pos.symbol || pos.ticker}</span>
                        <span className="text-[10px] text-outline truncate block max-w-[140px]">{pos.name}</span>
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface">
                        {pos.quantity}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface-variant">
                        {money(pos.avg_price_paid, pos.currency)}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface font-semibold">
                        {money(pos.current_price, pos.currency)}
                      </td>
                      <td className="py-2 px-space-sm text-right font-medium text-on-surface">
                        £{pos.current_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-2 px-space-sm text-right text-outline">
                        {portPercent}%
                      </td>
                      <td className="py-2 px-space-sm text-right">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[11px] font-bold ${
                            isPositive
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'bg-error/10 text-error border border-error/20'
                          }`}
                        >
                          {signedGbp(pos.unrealized_pnl_gbp)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Currency Exposure Donut & FX Risk Vector (4 Cols) */}
        <div className="xl:col-span-4 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
              <span className="font-headline-md text-headline-md text-on-surface font-semibold flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[18px] text-secondary">donut_large</span>
                Currency Exposure
              </span>
              <span className="font-label-caps text-label-caps text-outline">
                {hasLivePositions ? 'LIVE SYNC' : 'SAMPLE'}
              </span>
            </div>

            {/* Donut, arcs laid out from the position values rather than fixed dash offsets. */}
            <div className="flex items-center justify-center py-4">
              <div className="relative w-36 h-36">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="38" fill="none" stroke="#262a33" strokeWidth="12" />
                  {exposure.slices.map((slice, i) => {
                    const offset = exposure.slices
                      .slice(0, i)
                      .reduce((acc, s) => acc + (s.share / 100) * CIRCUMFERENCE, 0);
                    return (
                      <circle
                        key={slice.currency}
                        cx="50"
                        cy="50"
                        r="38"
                        fill="none"
                        stroke={EXPOSURE_COLOURS[i % EXPOSURE_COLOURS.length]}
                        strokeWidth="12"
                        strokeDasharray={`${(slice.share / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                        strokeDashoffset={-offset}
                        strokeLinecap="butt"
                      />
                    );
                  })}
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="font-data-mono-lg text-base font-bold text-on-surface">
                    {exposure.slices.length > 0 ? `${exposure.slices[0].share.toFixed(1)}%` : '—'}
                  </span>
                  <span className="font-label-caps text-[9px] text-primary uppercase">
                    {exposure.slices.length > 0 ? `${exposure.slices[0].currency} Dominated` : 'No Holdings'}
                  </span>
                </div>
              </div>
            </div>

            <div className="space-y-2 mt-2">
              {exposure.slices.map((slice, i) => (
                <div
                  key={slice.currency}
                  className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30"
                >
                  <div className="flex items-center gap-2">
                    <div
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: EXPOSURE_COLOURS[i % EXPOSURE_COLOURS.length] }}
                    />
                    <span className="font-body-sm text-xs text-on-surface">{slice.currency} Exposure</span>
                  </div>
                  <span className="font-data-mono-sm text-xs text-on-surface font-semibold">
                    {slice.share.toFixed(1)}% • £{(slice.value / 1000).toFixed(1)}k
                  </span>
                </div>
              ))}
            </div>
          </div>

          {exposure.foreign > 0 && (
            <div className="mt-4 p-2.5 rounded bg-surface-container-lowest border border-error/20 flex items-start gap-2 text-xs font-mono">
              <span className="material-symbols-outlined text-[16px] text-error flex-shrink-0">warning</span>
              <span className="text-[11px] text-on-surface-variant">
                FX Exposure Notice: {((exposure.foreign / exposure.total) * 100).toFixed(1)}% held in
                non-GBP instruments. A 1% GBP rally reduces valuation by ~£{(exposure.foreign * 0.01).toFixed(0)}.
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          4. ORDER HISTORY & EXECUTION TELEMETRY
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[18px] text-secondary">receipt_long</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold whitespace-nowrap">
              Order History & Execution Telemetry
            </span>
            {orders && (
              <span
                className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-caps text-[10px]"
                title="One row per execution: a part-filled order appears once per tranche, each with its own price and fee"
              >
                {orderItems.length} FILLS / {new Set(orderItems.map((o) => o.id)).size} ORDERS
              </span>
            )}
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
                      title={o.key}
                      // mousedown fires before the input's blur, so the click isn't lost
                      onMouseDown={(e) => {
                        e.preventDefault();
                        selectInstrument(o);
                      }}
                      onMouseEnter={() => setHighlightedSuggestion(i)}
                      className={`px-2 py-1.5 cursor-pointer flex items-center justify-between gap-2 ${
                        i === highlightedSuggestion ? 'bg-surface-container-high' : ''
                      }`}
                    >
                      <span className="text-on-surface truncate">{o.label}</span>
                      <span className="text-primary font-semibold shrink-0">{o.ticker}</span>
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
                ] as [OrderPeriod, string][]
              ).map(([period, label]) => (
                <button
                  key={period}
                  type="button"
                  onClick={() => setOrderPeriod(period)}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    orderPeriod === period
                      ? 'bg-surface-container-high text-primary font-bold'
                      : 'text-outline hover:text-on-surface'
                  }`}
                >
                  {label} ({instrumentOrders.filter((o) => inPeriod(o, period)).length})
                </button>
              ))}
            </div>

            {/* Side Pills (click again to clear) */}
            <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
              <button
                type="button"
                onClick={() => setOrderSide((s) => (s === 'BUY' ? 'ALL' : 'BUY'))}
                className={`px-2.5 py-1 rounded transition-colors ${
                  orderSide === 'BUY'
                    ? 'bg-surface-container-high text-primary font-bold'
                    : 'text-outline hover:text-on-surface'
                }`}
              >
                BUY ({periodOrders.filter((o) => o.side === 'BUY').length})
              </button>
              <button
                type="button"
                onClick={() => setOrderSide((s) => (s === 'SELL' ? 'ALL' : 'SELL'))}
                className={`px-2.5 py-1 rounded transition-colors ${
                  orderSide === 'SELL'
                    ? 'bg-surface-container-high text-tertiary font-bold'
                    : 'text-outline hover:text-on-surface'
                }`}
              >
                SELL ({periodOrders.filter((o) => o.side === 'SELL').length})
              </button>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
            <thead>
              <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                <th className="py-2 px-space-sm">Order / Fill</th>
                <th className="py-2 px-space-sm">Placed (UTC)</th>
                <th className="py-2 px-space-sm">Instrument</th>
                <th className="py-2 px-space-sm">Side</th>
                <th className="py-2 px-space-sm">Type</th>
                <th className="py-2 px-space-sm text-right">Fill Price</th>
                <th className="py-2 px-space-sm text-right">Filled / Ordered</th>
                <th className="py-2 px-space-sm text-right">Fees</th>
                <th className="py-2 px-space-sm text-right">Total Net</th>
                <th className="py-2 px-space-sm text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container/30">
              {filteredOrders.map((ord) => {
                const isFilled = ord.status === 'FILLED';
                return (
                  <tr key={ord.fill_id || ord.id} className="hover:bg-surface-container-high/40">
                    <td className="py-2 px-space-sm text-secondary font-mono">
                      {ord.id}
                      {/* Without this the 23 tranches of one order are 23 identical-looking rows. */}
                      {ord.fill_id && (
                        <span className="text-[10px] text-outline block">fill {ord.fill_id}</span>
                      )}
                    </td>
                    <td className="py-2 px-space-sm text-outline">{stamp(ord.created_at)}</td>
                    <td className="py-2 px-space-sm font-semibold text-on-surface">
                      {ord.symbol || ord.ticker}
                      <span className="text-[10px] text-outline block truncate max-w-[160px]">{ord.name}</span>
                    </td>
                    <td className="py-2 px-space-sm">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          ord.side === 'BUY'
                            ? 'bg-primary/10 text-primary border border-primary/20'
                            : 'bg-error/10 text-error border border-error/20'
                        }`}
                      >
                        {ord.side}
                      </span>
                    </td>
                    <td className="py-2 px-space-sm text-outline">{ord.type}</td>
                    <td className="py-2 px-space-sm text-right text-on-surface">
                      {ord.fill_price === null ? (
                        <span className="text-outline" title="No fill: this order never executed">—</span>
                      ) : (
                        money(ord.fill_price, ord.currency)
                      )}
                    </td>
                    <td className="py-2 px-space-sm text-right text-on-surface font-semibold">
                      {ord.filled_quantity ?? '—'}
                      <span className="text-outline"> / {ord.quantity ?? '—'}</span>
                    </td>
                    <td className="py-2 px-space-sm text-right text-outline">
                      {ord.fees === null ? '—' : money(Math.abs(ord.fees), ord.net_currency)}
                    </td>
                    <td className="py-2 px-space-sm text-right font-bold text-on-surface">
                      {ord.net_value === null ? (
                        <span className="text-outline font-normal">—</span>
                      ) : (
                        money(ord.net_value, ord.net_currency)
                      )}
                    </td>
                    <td className="py-2 px-space-sm text-center">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
                          isFilled
                            ? 'bg-primary-container/20 text-primary'
                            : 'bg-surface-container text-outline'
                        }`}
                      >
                        {ord.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {filteredOrders.length === 0 && (
            <div className="py-6 text-center font-body-sm text-xs text-outline">
              {orderItems.length === 0
                ? 'No order history loaded — sync with an API key to pull live executions.'
                : `No matching orders in ${orderPeriod === 'QUARTER' ? quarterLabel : orderPeriod === 'YEAR' ? 'the current year' : 'this selection'} — try a wider period.`}
            </div>
          )}
        </div>

        {orders?.truncated && (
          <div className="mt-space-sm pt-2 border-t border-surface-container/30 font-label-caps text-[10px] text-outline">
            MOST RECENT {orderItems.length} EXECUTIONS ONLY — the history endpoint allows 6
            requests per minute, so older pages are not fetched on load.
          </div>
        )}
      </div>

      {/* ─────────────────────────────────────────────────────────────
          5. DIVIDENDS BLOTTER & INCOME TELEMETRY
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[18px] text-tertiary-fixed">payments</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Dividends Blotter & Income Telemetry
            </span>
          </div>

          <div className="flex items-center gap-space-md text-xs font-mono">
            <span className="text-outline">
              {orders?.truncated || dividends?.truncated ? 'RECEIVED (WINDOW)' : 'TOTAL RECEIVED'}:{' '}
              <strong className="text-primary">
                {dividendTotals.length > 0
                  ? dividendTotals.map(([ccy, total]) => money(total, ccy)).join(' + ')
                  : '—'}
              </strong>
            </span>
            <span className="text-outline">
              PAYMENTS: <strong className="text-secondary">{dividendItems.length}</strong>
            </span>
            <span className="text-outline">
              INSTRUMENTS:{' '}
              <strong className="text-tertiary-fixed">
                {new Set(dividendItems.map((d) => d.ticker)).size}
              </strong>
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
            <thead>
              <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                <th className="py-2 px-space-sm">Paid On</th>
                <th className="py-2 px-space-sm">Ticker</th>
                <th className="py-2 px-space-sm">Instrument Name</th>
                <th className="py-2 px-space-sm text-right">Gross/Share</th>
                <th className="py-2 px-space-sm text-right">Quantity</th>
                <th className="py-2 px-space-sm text-right">Net Amount</th>
                <th className="py-2 px-space-sm">Type</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container/30">
              {dividendItems.map((div, idx) => (
                <tr key={`${div.ticker}-${div.paid_on}-${idx}`} className="hover:bg-surface-container-high/40">
                  <td className="py-2 px-space-sm text-outline">{isoDate(div.paid_on) ?? '—'}</td>
                  <td className="py-2 px-space-sm font-bold text-primary">{div.symbol || div.ticker}</td>
                  <td className="py-2 px-space-sm text-on-surface">{div.name}</td>
                  <td className="py-2 px-space-sm text-right text-on-surface-variant">
                    {money(div.gross_per_share, div.instrument_currency, 4)}
                  </td>
                  <td className="py-2 px-space-sm text-right text-on-surface-variant">
                    {div.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </td>
                  <td className="py-2 px-space-sm text-right font-bold text-primary">
                    {money(div.amount, div.currency)}
                  </td>
                  <td className="py-2 px-space-sm text-outline">{div.type}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {dividendItems.length === 0 && (
            <div className="py-6 text-center font-body-sm text-xs text-outline">
              No dividend payments loaded — sync with an API key to pull live income.
            </div>
          )}
        </div>

        <div className="mt-space-sm pt-2 border-t border-surface-container/30 font-label-caps text-[10px] text-outline">
          NET OF WITHHOLDING. The API reports neither the tax withheld nor the treaty regime, and
          the gap between gross/share and the net amount is withholding and FX combined, so neither
          can be separated out here.
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          FLOATING WINDOW: Single Instrument Inspector
      ───────────────────────────────────────────────────────────── */}
      {inspected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setInspectedTicker(null)}
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
                  onClick={() => setInspectedTicker(null)}
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
                    FOCUSED INSTRUMENT: {inspected.symbol || inspected.ticker} • {inspected.name}
                  </div>
                </div>
              </div>

              {/* Instrument Dropdown Selector */}
              <div className="flex items-center gap-space-sm">
                <span className="font-label-caps text-label-caps text-on-surface-variant">SWITCH TICKER:</span>
                <select
                  value={inspected.ticker}
                  onChange={(e) => setInspectedTicker(e.target.value)}
                  className="px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-primary font-bold focus:outline-none focus:border-primary"
                >
                  {displayPositions.map((p) => (
                    <option key={p.ticker} value={p.ticker}>
                      {p.symbol || p.ticker} — {p.name}
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
                  {inspected.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })} Shares
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">
                  AVG PRICE PAID ({inspected.currency})
                </span>
                <span className="font-data-mono-lg text-sm text-on-surface font-semibold">
                  {money(inspected.avg_price_paid, inspected.currency)}
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">CURRENT VALUE (GBP)</span>
                <span className="font-data-mono-lg text-sm text-on-surface font-semibold">
                  £{inspected.current_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="p-2.5 rounded bg-surface-container-lowest border border-surface-container/40">
                <span className="font-label-caps text-[10px] text-outline block">NET UNREALISED P&L</span>
                <span className={`font-data-mono-lg text-sm font-semibold ${inspected.unrealized_pnl_gbp >= 0 ? 'text-primary' : 'text-error'}`}>
                  {signedGbp(inspected.unrealized_pnl_gbp)}
                </span>
              </div>
            </div>

            {/* Inspector Chart & Execution History */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-md">
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

                {inspected.symbol ? (
                  <PriceTradeChart ticker={inspected.symbol} trades={chartTrades} />
                ) : (
                  <div className="py-10 text-center font-body-sm text-xs text-outline">
                    No market symbol for {inspected.ticker}. Trading 212 lists this instrument on a
                    venue the price provider does not cover, so there is no series to chart.
                  </div>
                )}
              </div>

              {/* Single Instrument Fills (4 cols) */}
              <div className="lg:col-span-4 bg-surface-container-lowest p-space-sm rounded-lg border border-surface-container/40">
                <span className="font-label-caps text-label-caps text-outline block mb-2 uppercase">
                  Recorded Fills ({inspectedFills.length})
                </span>
                {inspectedFills.length === 0 ? (
                  <p className="font-body-sm text-xs text-outline py-4">
                    {orderItems.length === 0
                      ? 'No order history loaded.'
                      : 'No fills for this instrument in the fetched history window.'}
                  </p>
                ) : (
                  // Capped: one instrument here has 63 fills, which otherwise stretches the
                  // dialog past the viewport and leaves the chart beside a column of whitespace.
                  <div className="max-h-[340px] overflow-y-auto">
                  <table className="w-full text-left font-data-mono-sm text-[11px]">
                    <thead className="sticky top-0 bg-surface-container-lowest">
                      <tr className="text-outline uppercase font-label-caps text-[9px] border-b border-surface-container/40">
                        <th className="py-1">Filled</th>
                        <th className="py-1">Side</th>
                        <th className="py-1 text-right">Qty</th>
                        <th className="py-1 text-right">Price</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-container/20">
                      {inspectedFills.map((o) => (
                        <tr key={o.fill_id || o.id}>
                          <td className="py-1 text-outline">{isoDate(o.filled_at) ?? '—'}</td>
                          <td className={`py-1 font-bold ${o.side === 'BUY' ? 'text-primary' : 'text-tertiary'}`}>
                            {o.side}
                          </td>
                          <td className="py-1 text-right text-on-surface">{o.filled_quantity}</td>
                          <td className="py-1 text-right text-on-surface">
                            {money(o.fill_price ?? 0, o.currency)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
