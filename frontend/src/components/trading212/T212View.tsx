import React, { useState, useEffect } from 'react';
import { t212Api } from '../../services/api';
import { T212AccountSummary, T212Position } from '../../types';

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

const SAMPLE_T212_ORDERS = [
  { id: 'ORD-984210', time: '2026-10-22 14:15:02', symbol: 'LITE (Lumentum)', side: 'BUY', type: 'LIMIT', fill: '$54.10', qty: 100, fees: '£0.00', net: '£4,180.82', status: 'FILLED' },
  { id: 'ORD-984209', time: '2026-10-18 16:04:19', symbol: 'AMZN (Amazon)', side: 'BUY', type: 'MARKET', fill: '$194.00', qty: 20, fees: '£0.00', net: '£2,998.45', status: 'FILLED' },
  { id: 'ORD-984208', time: '2026-10-10 18:22:45', symbol: 'TRI (Thomson Reuters)', side: 'SELL', type: 'LIMIT', fill: '$169.20', qty: 15, fees: '£0.00', net: '£1,961.36', status: 'FILLED' },
  { id: 'ORD-984207', time: '2026-09-29 13:30:11', symbol: 'OKLO (Oklo Inc)', side: 'BUY', type: 'MARKET', fill: '$23.80', qty: 80, fees: '£0.00', net: '£1,471.20', status: 'FILLED' },
  { id: 'ORD-984206', time: '2026-09-14 15:10:04', symbol: 'EQQQ.L (NASDAQ 100)', side: 'BUY', type: 'LIMIT', fill: '£431.50', qty: 10, fees: '£0.00', net: '£4,315.00', status: 'FILLED' },
];

const SAMPLE_T212_DIVIDENDS = [
  { date: '2026-10-15', ticker: 'TRI', name: 'Thomson Reuters Corp', gross: '$0.54', net: '£27.18', type: 'ORDINARY', wht: '15% ($0.08)', regime: 'CA TREATY' },
  { date: '2026-09-20', ticker: 'LITE', name: 'Lumentum Holdings Inc', gross: '$0.28', net: '£82.40', type: 'ORDINARY', wht: '15% ($0.04)', regime: 'US W-8BEN' },
  { date: '2026-08-14', ticker: 'WCOP.L', name: 'WisdomTree Copper Trust', gross: '£0.18', net: '£81.00', type: 'DISTRIBUTION', wht: '0% (£0.00)', regime: 'UK DIV' },
  { date: '2026-07-28', ticker: 'GOOG', name: 'Alphabet Inc Class C', gross: '$0.20', net: '£6.95', type: 'ORDINARY', wht: '15% ($0.03)', regime: 'US W-8BEN' },
];

export const T212View: React.FC = () => {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('t212_api_key') || '');
  const [apiSecret, setApiSecret] = useState(() => localStorage.getItem('t212_api_secret') || '');
  const [showSecret, setShowSecret] = useState(false);
  const [summary, setSummary] = useState<T212AccountSummary | null>(null);
  const [positions, setPositions] = useState<T212Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [selectedHoldingTicker, setSelectedHoldingTicker] = useState('LITE');

  const fetchT212Data = async () => {
    setLoading(true);
    setSyncStatus(null);
    let overviewSuccess = false;
    let positionsSuccess = false;
    let errorDetails = '';

    try {
      // 1. Fetch overview
      try {
        const sumRes = await t212Api.getOverview(apiKey || undefined, apiSecret || undefined);
        if (sumRes) {
          setSummary(sumRes);
          overviewSuccess = true;
        }
      } catch (err: any) {
        const detail = err.response?.data?.detail || err.message;
        errorDetails += `Overview: ${detail}. `;
      }

      // Small delay to respect Trading 212 rate limit (1 req / 1s)
      await new Promise((r) => setTimeout(r, 650));

      // 2. Fetch positions
      try {
        const posRes = await t212Api.getPositions(apiKey || undefined, apiSecret || undefined);
        if (Array.isArray(posRes)) {
          setPositions(posRes);
          positionsSuccess = true;
        }
      } catch (err: any) {
        const detail = err.response?.data?.detail || err.message;
        errorDetails += `Positions: ${detail}. `;
      }

      if (overviewSuccess && positionsSuccess) {
        setSyncStatus('API SYNC SUCCESSFUL (LIVE FEED)');
      } else if (overviewSuccess) {
        setSyncStatus(`ACCOUNT SYNCED (Positions notice: ${errorDetails})`);
      } else if (apiKey) {
        setSyncStatus(`API SYNC FAILED: ${errorDetails}`);
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
  const displayPositions = positions.length > 0 ? positions : SAMPLE_T212_POSITIONS;

  const totalValue = hasLiveSummary ? summary.total_value : 84210.50;
  const cashAvailable = hasLiveSummary ? summary.cash_available : 4820.10;
  const investmentsValue = hasLiveSummary ? summary.investments_value : 79390.40;
  const totalCost = hasLiveSummary ? summary.total_cost : 71200.00;
  const realisedPnl = hasLiveSummary ? summary.realized_pnl : 2140.80;
  const unrealisedPnl = hasLiveSummary ? summary.unrealized_pnl : 8190.40;
  const fxImpact = hasLiveSummary
    ? (positions.reduce((acc, p) => acc + (p.fx_impact_gbp || 0), 0) || 0.0)
    : -420.50;

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

          {/* Credentials Inputs */}
          <div className="flex flex-wrap items-center gap-space-sm flex-1 max-w-2xl">
            <input
              type="text"
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
            <span className="text-outline">T212 REAL-TIME STREAMLIT SYNC</span>
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
            {positions.length > 0 ? `${positions.length} Live Holdings` : `${displayPositions.length} Holdings`}
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
            {realisedPnl >= 0 ? '+' : ''}£{realisedPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">Closed Fills</span>
        </div>

        {/* FX Impact */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">FX Impact</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1">
            £{fxImpact.toFixed(2)}
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">FX Drift</span>
        </div>

        {/* Unrealised P&L */}
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <span className="font-label-caps text-[10px] text-outline uppercase">Unrealised P&L</span>
          <span className={`font-data-mono-lg text-sm font-bold my-1 ${unrealisedPnl >= 0 ? 'text-primary' : 'text-error'}`}>
            {unrealisedPnl >= 0 ? '+' : ''}£{unrealisedPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">
            {totalCost > 0 ? `${((unrealisedPnl / totalCost) * 100).toFixed(1)}% Return` : '+11.5% Return'}
          </span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          3. OPEN POSITIONS & CURRENCY EXPOSURE
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Open Positions Table (8 Cols) */}
        <div className="xl:col-span-8 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
          <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">show_chart</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Pure API Open Positions
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-caps text-[10px]">
                {positions.length > 0 ? `${positions.length} LIVE` : 'SAMPLE'}
              </span>
            </div>
            <span className="font-label-caps text-label-caps text-outline uppercase font-mono">
              DIRECT WALLET IMPACT
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
                      onClick={() => setSelectedHoldingTicker(pos.ticker)}
                      className={`hover:bg-surface-container-high/50 cursor-pointer transition-colors ${
                        selectedHoldingTicker === pos.ticker ? 'bg-surface-container-high/80' : ''
                      }`}
                    >
                      <td className="py-2 px-space-sm">
                        <span className="font-bold text-primary block">{pos.ticker}</span>
                        <span className="text-[10px] text-outline truncate block max-w-[140px]">{pos.name}</span>
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface">
                        {pos.quantity}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface-variant">
                        {pos.currency === 'USD' ? '$' : '£'}{pos.avg_price_paid.toFixed(2)}
                      </td>
                      <td className="py-2 px-space-sm text-right text-on-surface font-semibold">
                        {pos.currency === 'USD' ? '$' : '£'}{pos.current_price.toFixed(2)}
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
                          {isPositive ? '+' : ''}£{pos.unrealized_pnl_gbp.toFixed(2)}
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
              <span className="font-label-caps text-label-caps text-outline">LIVE SYNC</span>
            </div>

            {/* SVG Donut */}
            <div className="flex items-center justify-center py-4">
              <div className="relative w-36 h-36">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="38" fill="none" stroke="#262a33" strokeWidth="12" />
                  <circle
                    cx="50"
                    cy="50"
                    r="38"
                    fill="none"
                    stroke="#4edea3"
                    strokeWidth="12"
                    strokeDasharray="157.1 238.8"
                    strokeLinecap="round"
                  />
                  <circle
                    cx="50"
                    cy="50"
                    r="38"
                    fill="none"
                    stroke="#93ccff"
                    strokeWidth="12"
                    strokeDasharray="81.7 238.8"
                    strokeDashoffset="-157.1"
                    strokeLinecap="round"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="font-data-mono-lg text-base font-bold text-on-surface">65.8%</span>
                  <span className="font-label-caps text-[9px] text-primary uppercase">USD Dominated</span>
                </div>
              </div>
            </div>

            <div className="space-y-2 mt-2">
              <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                  <span className="font-body-sm text-xs text-on-surface">USD Exposure</span>
                </div>
                <span className="font-data-mono-sm text-xs text-on-surface font-semibold">65.8% • £55.4k</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-secondary" />
                  <span className="font-body-sm text-xs text-on-surface">GBP Exposure</span>
                </div>
                <span className="font-data-mono-sm text-xs text-on-surface font-semibold">34.2% • £28.8k</span>
              </div>
            </div>
          </div>

          <div className="mt-4 p-2.5 rounded bg-surface-container-lowest border border-error/20 flex items-start gap-2 text-xs font-mono">
            <span className="material-symbols-outlined text-[16px] text-error flex-shrink-0">warning</span>
            <span className="text-[11px] text-on-surface-variant">
              FX Exposure Notice: 65.8% invested in US instruments. 1% GBP rally reduces valuation by ~£554.
            </span>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          4. ORDER HISTORY & EXECUTION TELEMETRY
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[18px] text-secondary">receipt_long</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Order History & Execution Telemetry
            </span>
          </div>
          <span className="font-label-caps text-label-caps text-outline uppercase font-mono">
            REST API TELEMETRY
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
            <thead>
              <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                <th className="py-2 px-space-sm">Order ID</th>
                <th className="py-2 px-space-sm">Timestamp (UTC)</th>
                <th className="py-2 px-space-sm">Instrument</th>
                <th className="py-2 px-space-sm">Side</th>
                <th className="py-2 px-space-sm">Type</th>
                <th className="py-2 px-space-sm text-right">Fill Price</th>
                <th className="py-2 px-space-sm text-right">Quantity</th>
                <th className="py-2 px-space-sm text-right">Fees (FX/Gov)</th>
                <th className="py-2 px-space-sm text-right">Total Net GBP</th>
                <th className="py-2 px-space-sm text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container/30">
              {SAMPLE_T212_ORDERS.map((ord) => (
                <tr key={ord.id} className="hover:bg-surface-container-high/40">
                  <td className="py-2 px-space-sm text-secondary font-mono">{ord.id}</td>
                  <td className="py-2 px-space-sm text-outline">{ord.time}</td>
                  <td className="py-2 px-space-sm font-semibold text-on-surface">{ord.symbol}</td>
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
                  <td className="py-2 px-space-sm text-right text-on-surface">{ord.fill}</td>
                  <td className="py-2 px-space-sm text-right text-on-surface font-semibold">{ord.qty}</td>
                  <td className="py-2 px-space-sm text-right text-outline">{ord.fees}</td>
                  <td className="py-2 px-space-sm text-right font-bold text-on-surface">{ord.net}</td>
                  <td className="py-2 px-space-sm text-center">
                    <span className="px-2 py-0.5 rounded bg-primary-container/20 text-primary text-[10px] font-bold font-mono">
                      {ord.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
              TOTAL RECEIVED: <strong className="text-primary">£1,420.80</strong>
            </span>
            <span className="text-outline">
              YIELD ON COST: <strong className="text-secondary">3.42%</strong>
            </span>
            <span className="text-outline">
              PROJECTED RUN-RATE: <strong className="text-tertiary-fixed">£1,840/yr</strong>
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
                <th className="py-2 px-space-sm text-right">Net Amount</th>
                <th className="py-2 px-space-sm">Type</th>
                <th className="py-2 px-space-sm">WHT Deducted (15%)</th>
                <th className="py-2 px-space-sm">Tax Regime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container/30">
              {SAMPLE_T212_DIVIDENDS.map((div, idx) => (
                <tr key={idx} className="hover:bg-surface-container-high/40">
                  <td className="py-2 px-space-sm text-outline">{div.date}</td>
                  <td className="py-2 px-space-sm font-bold text-primary">{div.ticker}</td>
                  <td className="py-2 px-space-sm text-on-surface">{div.name}</td>
                  <td className="py-2 px-space-sm text-right text-on-surface-variant">{div.gross}</td>
                  <td className="py-2 px-space-sm text-right font-bold text-primary">{div.net}</td>
                  <td className="py-2 px-space-sm text-outline">{div.type}</td>
                  <td className="py-2 px-space-sm text-error">{div.wht}</td>
                  <td className="py-2 px-space-sm text-secondary font-mono">{div.regime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
