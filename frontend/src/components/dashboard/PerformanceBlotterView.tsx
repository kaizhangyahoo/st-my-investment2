import React, { useState, useEffect, useMemo } from 'react';
import { portfolioApi } from '../../services/api';
import { PortfolioHistoryPoint, PortfolioHistoryResponse, FeedState } from '../../types';

type Timeframe = '1M' | '3M' | '6M' | '1Y' | 'ALL';

const TIMEFRAME_MONTHS: Record<Exclude<Timeframe, 'ALL'>, number> = {
  '1M': 1,
  '3M': 3,
  '6M': 6,
  '1Y': 12,
};

// SVG plot area inside the 900x240 viewBox.
const PLOT = { left: 50, right: 870, top: 40, bottom: 210 };
const GRID_Y = [40, 90, 140, 190];

const STATUS: Record<FeedState, { label: string; text: string; dot: string }> = {
  loading: { label: 'COMPUTING…', text: 'text-amber-400', dot: 'bg-amber-400' },
  live: { label: 'COMPUTED', text: 'text-primary', dot: 'bg-primary' },
  partial: { label: 'PARTIAL', text: 'text-amber-400', dot: 'bg-amber-400' },
  degraded: { label: 'DEGRADED', text: 'text-error', dot: 'bg-error' },
  offline: { label: 'FEED_ERROR', text: 'text-error', dot: 'bg-error' },
};

const deriveState = (res: PortfolioHistoryResponse): { state: FeedState; detail: string[] } => {
  const dq = res.data_quality;
  const detail: string[] = [];
  if (dq.fx_fallback) {
    detail.push('FX rates unavailable — non-GBP valuations are estimates, not real quotes');
  }
  if (dq.unpriced_tickers.length) {
    detail.push(`No history from any provider: ${dq.unpriced_tickers.join(', ')}`);
  }
  dq.unconvertible.forEach((u) =>
    detail.push(`${u.ticker} quotes in ${u.currency} — no GBP cross, dates holding it are dropped`),
  );
  if (dq.skipped_dates) {
    detail.push(`${dq.skipped_dates} trading day(s) dropped — an open position had no close`);
  }
  if (dq.degraded) return { state: 'degraded', detail };
  if (detail.length) return { state: 'partial', detail };
  return { state: 'live', detail: [`${res.points.length} trading days valued`] };
};

const money = (v: number, dp = 2) =>
  v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });

const axisLabel = (v: number) =>
  Math.abs(v) >= 1000 ? `£${Math.round(v / 1000)}k` : `£${Math.round(v)}`;

const buildCurve = (points: PortfolioHistoryPoint[]) => {
  if (points.length === 0) return null;
  const values = points.map((p) => p.value);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  const lastIndex = points.length - 1;
  const x = (i: number) =>
    lastIndex === 0
      ? (PLOT.left + PLOT.right) / 2
      : PLOT.left + (i / lastIndex) * (PLOT.right - PLOT.left);
  const y = (v: number) => PLOT.bottom - ((v - min) / span) * (PLOT.bottom - PLOT.top);

  const coords = points.map((p, i) => `${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`);
  const line = `M ${coords.join(' L ')}`;
  return {
    line,
    area: `${line} L ${x(lastIndex).toFixed(1)} ${PLOT.bottom} L ${PLOT.left} ${PLOT.bottom} Z`,
    gridValues: GRID_Y.map((gy) => min + ((PLOT.bottom - gy) / (PLOT.bottom - PLOT.top)) * span),
    lastX: x(lastIndex),
    lastY: y(points[lastIndex].value),
  };
};

export const PerformanceBlotterView: React.FC = () => {
  const [response, setResponse] = useState<PortfolioHistoryResponse | null>(null);
  const [status, setStatus] = useState<{ state: FeedState; detail: string[] }>({
    state: 'loading',
    detail: [],
  });
  const [timeframe, setTimeframe] = useState<Timeframe>('ALL');

  useEffect(() => {
    const load = async () => {
      setStatus({ state: 'loading', detail: [] });
      try {
        const data = await portfolioApi.getHistory();
        setResponse(data);
        setStatus(deriveState(data));
      } catch (err: any) {
        // Never swallowed: a silent failure used to be indistinguishable from a real series,
        // because this view substituted hardcoded sample points.
        console.error('Failed to load portfolio history', err);
        setResponse(null);
        setStatus({
          state: 'offline',
          detail: [
            `GET /api/v1/portfolio/history failed: ${err?.message ?? 'unknown error'}`,
            err?.code === 'ECONNABORTED'
              ? 'Request timed out after 60s — is the backend running?'
              : 'Check that the backend is reachable.',
          ],
        });
      }
    };
    load();
  }, []);

  const points = response?.points ?? [];

  const visible = useMemo(() => {
    if (timeframe === 'ALL' || points.length === 0) return points;
    const last = new Date(points[points.length - 1].date);
    const cutoff = new Date(last);
    cutoff.setMonth(cutoff.getMonth() - TIMEFRAME_MONTHS[timeframe]);
    return points.filter((p) => new Date(p.date) >= cutoff);
  }, [points, timeframe]);

  const curve = useMemo(() => buildCurve(visible), [visible]);
  const presentation = STATUS[status.state];

  const first = visible[0];
  const last = visible[visible.length - 1];
  const absoluteReturn = first && last ? last.value - first.value : null;
  const percentReturn =
    absoluteReturn !== null && first && first.value !== 0
      ? (absoluteReturn / first.value) * 100
      : null;
  const signed = (v: number) => (v >= 0 ? '+' : '−');
  const returnColour = absoluteReturn === null || absoluteReturn >= 0 ? 'text-primary' : 'text-error';

  return (
    <div className="space-y-space-lg pb-16">
      {/* 1. HEADER TELEMETRY STRIP */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-space-md">
        <div className="flex items-center gap-space-sm">
          <span className="material-symbols-outlined text-[20px] text-primary">candlestick_chart</span>
          <div>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Performance Blotter & Historical Alpha Telemetry
            </span>
            <span className="font-label-caps text-[10px] text-outline block">
              PORTFOLIO HISTORY OVER TIME • COMPUTED FROM YOUR UPLOADED TRADE HISTORY
            </span>
          </div>
        </div>

        <div className="flex items-center gap-space-sm">
          <span
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono font-medium ${presentation.text}`}
            title={status.detail.join('\n')}
          >
            <span className={`w-2 h-2 rounded-full ${presentation.dot}`} />
            {presentation.label}
          </span>

          <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
            {(['1M', '3M', '6M', '1Y', 'ALL'] as const).map((tf) => (
              <button
                key={tf}
                type="button"
                onClick={() => setTimeframe(tf)}
                className={`px-2 py-0.5 rounded transition-colors ${
                  timeframe === tf
                    ? 'bg-surface-container-high text-primary font-bold'
                    : 'text-outline hover:text-on-surface'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {status.detail.length > 0 && status.state !== 'live' && (
        <ul className="bg-surface-container-low p-space-md rounded-xl border border-error/40 text-xs font-mono text-on-surface-variant space-y-1">
          {status.detail.map((d) => (
            <li key={d} className="flex gap-2">
              <span className="text-error">!</span>
              {d}
            </li>
          ))}
        </ul>
      )}

      {/* 2. RISK & RETURN METRICS */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-space-sm">
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Cumulative Return</span>
          <span className={`font-data-mono-lg text-sm font-bold my-1 block ${returnColour}`}>
            {percentReturn === null ? '—' : `${signed(percentReturn)}${Math.abs(percentReturn).toFixed(1)}%`}
          </span>
          <span className={`font-data-mono-sm text-[10px] ${returnColour}`}>
            {absoluteReturn === null
              ? 'No series'
              : `${signed(absoluteReturn)}£${money(Math.abs(absoluteReturn))}`}
          </span>
        </div>

        {/* Sharpe needs a risk-free rate and the rest need per-position realised P&L; none of
            that is wired up yet, so they report as unavailable rather than showing a number. */}
        {['Sharpe Ratio', 'Max Drawdown', 'Ann. Volatility', 'Win Rate'].map((label) => (
          <div
            key={label}
            className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm"
          >
            <span className="font-label-caps text-[10px] text-outline uppercase block">{label}</span>
            <span className="font-data-mono-lg text-sm text-outline font-bold my-1 block">—</span>
            <span className="font-data-mono-sm text-[10px] text-outline">Not yet computed</span>
          </div>
        ))}
      </div>

      {/* 3. EQUITY CURVE */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-primary">ssid_chart</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Consolidated Equity Curve (GBP)
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="flex items-center gap-1.5 text-primary">
              <span className="w-3 h-0.5 bg-primary" />
              PORTFOLIO VALUE
            </span>
            {response && (
              <span className="text-outline">
                AS OF {new Date(response.computed_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>

        <div className="bg-surface-container-lowest p-space-md rounded-lg border border-surface-container/40">
          {curve === null ? (
            <div className="h-72 flex flex-col items-center justify-center gap-2 text-center">
              <span className="material-symbols-outlined text-[28px] text-outline">
                {status.state === 'loading' ? 'hourglass_top' : 'show_chart'}
              </span>
              <span className="font-data-mono-sm text-sm text-on-surface-variant">
                {status.state === 'loading'
                  ? 'Computing historical values…'
                  : status.state === 'offline'
                    ? 'Could not load the history series.'
                    : 'No historical values for this portfolio.'}
              </span>
              <span className="font-data-mono-sm text-[10px] text-outline max-w-md">
                {status.state === 'loading'
                  ? 'Each trading day is valued against that day’s closes and FX.'
                  : 'Upload a trade history on the IG CSV tab — nothing is charted until there is a real series.'}
              </span>
            </div>
          ) : (
            <svg className="w-full h-72" viewBox="0 0 900 240">
              <defs>
                <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#4edea3" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#4edea3" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {GRID_Y.map((gy, i) => (
                <g key={gy}>
                  <line x1={PLOT.left - 10} y1={gy} x2={PLOT.right + 10} y2={gy} stroke="#1c2028" strokeDasharray="3,3" />
                  <text x={PLOT.left - 15} y={gy + 4} fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">
                    {axisLabel(curve.gridValues[i])}
                  </text>
                </g>
              ))}
              <line x1={PLOT.left - 10} y1={PLOT.bottom} x2={PLOT.right + 10} y2={PLOT.bottom} stroke="#262a33" />

              <path d={curve.area} fill="url(#equityGradient)" />
              <path d={curve.line} fill="none" stroke="#4edea3" strokeWidth="2.5" strokeLinecap="round" />

              <circle cx={curve.lastX} cy={curve.lastY} r="5" fill="#4edea3" />
              <text
                x={curve.lastX}
                y={Math.max(curve.lastY - 14, 14)}
                fill="#4edea3"
                fontSize="11"
                textAnchor="end"
                fontFamily="monospace"
                fontWeight="bold"
              >
                LATEST: £{money(last.value, 0)}
              </text>

              <text x={PLOT.left} y="228" fill="#86948a" fontSize="10" fontFamily="monospace">
                {first.date}
              </text>
              <text x={PLOT.right} y="228" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">
                {last.date}
              </text>
              <text x={(PLOT.left + PLOT.right) / 2} y="228" fill="#86948a" fontSize="10" textAnchor="middle" fontFamily="monospace">
                {visible.length} TRADING DAYS
              </text>
            </svg>
          )}
        </div>
      </div>
    </div>
  );
};
