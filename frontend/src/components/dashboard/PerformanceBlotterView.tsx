import React, { useState, useEffect, useMemo } from 'react';
import { portfolioApi } from '../../services/api';
import {
  BenchmarkResponse,
  FeedState,
  PortfolioHistoryResponse,
  PortfolioMetricsResponse,
  RealisedMetrics,
  RiskMetrics,
} from '../../types';
import { EquityCurveChart } from './EquityCurveChart';

type Timeframe = '1M' | '3M' | '6M' | '1Y' | 'ALL';

const TIMEFRAME_MONTHS: Record<Exclude<Timeframe, 'ALL'>, number> = {
  '1M': 1,
  '3M': 3,
  '6M': 6,
  '1Y': 12,
};

const STATUS: Record<FeedState, { label: string; text: string; dot: string }> = {
  loading: { label: 'LOADING…', text: 'text-amber-400', dot: 'bg-amber-400' },
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

const signed = (v: number) => (v >= 0 ? '+' : '−');

const percent = (v: number | null, dp = 1) =>
  v === null ? '—' : `${signed(v)}${Math.abs(v).toFixed(dp)}%`;

/** A tile shows a figure only when the backend computed one; a null stays a dash. */
const MetricTile: React.FC<{
  label: string;
  value: string;
  caption: string;
  tone?: string;
}> = ({ label, value, caption, tone = 'text-on-surface' }) => (
  <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
    <span className="font-label-caps text-[10px] text-outline uppercase block">{label}</span>
    <span className={`font-data-mono-lg text-sm font-bold my-1 block ${tone}`}>{value}</span>
    <span className={`font-data-mono-sm text-[10px] ${tone === 'text-outline' ? 'text-outline' : 'text-on-surface-variant'}`}>
      {caption}
    </span>
  </div>
);

export const PerformanceBlotterView: React.FC = () => {
  const [response, setResponse] = useState<PortfolioHistoryResponse | null>(null);
  const [metrics, setMetrics] = useState<PortfolioMetricsResponse | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResponse | null>(null);
  const [benchmarkError, setBenchmarkError] = useState<string | null>(null);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [status, setStatus] = useState<{ state: FeedState; detail: string[] }>({
    state: 'loading',
    detail: [],
  });
  const [timeframe, setTimeframe] = useState<Timeframe>('ALL');
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [accounts, setAccounts] = useState<string[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [computing, setComputing] = useState(false);
  const [computeReport, setComputeReport] = useState<string[]>([]);

  const recompute = async () => {
    setComputing(true);
    try {
      const res = await portfolioApi.computeHistory();
      setComputeReport(deriveState(res).detail.map((d) => `Last compute: ${d}`));
    } catch (err: any) {
      setComputeReport([`POST /api/v1/portfolio/history/compute failed: ${err?.message ?? 'unknown error'}`]);
    } finally {
      setComputing(false);
      setReloadKey((k) => k + 1);
    }
  };

  useEffect(() => {
    const load = async () => {
      setStatus({ state: 'loading', detail: [] });
      try {
        const data = await portfolioApi.getHistory(accountId);
        setResponse(data);
        setAccounts(data.accounts ?? []);
        setStatus(deriveState(data));
        // Statistics are a separate request, so losing them leaves the curve intact and only
        // the tiles unavailable.
        try {
          setMetrics(await portfolioApi.getMetrics(data.account_id ?? accountId));
        } catch (metricsErr) {
          console.error('Failed to load portfolio metrics', metricsErr);
          setMetrics(null);
        }
      } catch (err: any) {
        // Never swallowed: a silent failure used to be indistinguishable from a real series,
        // because this view substituted hardcoded sample points.
        console.error('Failed to load portfolio history', err);
        setResponse(null);
        setMetrics(null);
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
  }, [accountId, reloadKey]);

  const points = response?.points ?? [];
  // Before the first click the backend picks the account, so the highlight comes from the
  // response; after one, from local state, so the button reacts before the fetch returns.
  const selectedAccount = accountId ?? response?.account_id;

  const stats: RiskMetrics | null = metrics?.windows[timeframe] ?? null;
  const realised: RealisedMetrics | null = metrics?.realised[timeframe] ?? null;

  // The backend cut the window the tiles describe, so the curve is filtered by that same
  // boundary; its own month arithmetic is only the fallback for a failed metrics request.
  const visible = useMemo(() => {
    if (timeframe === 'ALL' || points.length === 0) return points;
    if (stats?.start_date) {
      const start = stats.start_date;
      return points.filter((p) => p.date >= start);
    }
    const cutoff = new Date(points[points.length - 1].date);
    cutoff.setMonth(cutoff.getMonth() - TIMEFRAME_MONTHS[timeframe]);
    return points.filter((p) => new Date(p.date) >= cutoff);
  }, [points, timeframe, stats]);

  useEffect(() => {
    if (!showBenchmark || benchmark || points.length === 0) return;
    let cancelled = false;
    setBenchmarkError(null);
    portfolioApi
      .getBenchmark(points[0].date)
      .then((res) => {
        if (cancelled) return;
        setBenchmark(res);
        if (res.unavailable_reason) setBenchmarkError(res.unavailable_reason);
      })
      .catch((err: any) => {
        if (!cancelled) setBenchmarkError(err?.message ?? 'benchmark request failed');
      });
    return () => {
      cancelled = true;
    };
  }, [showBenchmark, benchmark, points]);

  const presentation = STATUS[status.state];
  const last = visible[visible.length - 1];
  const returnTone =
    stats?.cumulative_return_pct == null || stats.cumulative_return_pct >= 0
      ? 'text-primary'
      : 'text-error';
  // Why there is no win rate, in the order the user can act on: no statement at all, then nothing
  // closed in this window. Saying "0%" for either would be a measurement neither supports.
  const coverage = metrics?.realised_coverage ?? null;
  const winRateCaption = () => {
    if (coverage?.unavailable_reason) return 'Upload a trade statement to measure';
    if (realised == null || realised.realised_pnl_gbp == null) return 'No closed trades in window';
    const excluded = coverage?.excluded_disposals
      ? `, ${coverage.excluded_disposals} without a cost basis`
      : '';
    // The statement and the value series do not end on the same date, so when this window really
    // covers a different period the tile states it rather than letting the curve's stand in.
    const period =
      realised.end_date && realised.end_date !== stats?.end_date ? ` to ${realised.end_date}` : '';
    return `${realised.winning_disposals}/${realised.disposals} closed${period}, ${signed(realised.realised_pnl_gbp)}£${money(Math.abs(realised.realised_pnl_gbp))} realised${excluded}`;
  };
  const benchmarkPoints = benchmark && benchmark.points.length > 0 ? benchmark : null;

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
              PORTFOLIO HISTORY OVER TIME • FROM STORED PORTFOLIO VALUES
            </span>
          </div>
        </div>

        <div className="flex items-center gap-space-sm">
          {accounts.length > 0 && (
            <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
              {accounts.map((acc) => (
                <button
                  key={acc}
                  type="button"
                  onClick={() => setAccountId(acc)}
                  className={`px-2 py-0.5 rounded transition-colors ${
                    selectedAccount === acc
                      ? 'bg-surface-container-high text-primary font-bold'
                      : 'text-outline hover:text-on-surface'
                  }`}
                >
                  {acc}
                </button>
              ))}
            </div>
          )}
          {/* This panel only reads stored values, so there is normally nothing to compute.
              The backend offers this when the series it would write stops short of today. */}
          {response?.fillable_gap && (
            <button
              type="button"
              onClick={recompute}
              disabled={computing}
              title="This account's series stops before today — value the uploaded trade history to extend it"
              className="px-2 py-1 rounded border border-surface-container text-xs font-mono text-outline hover:text-on-surface disabled:opacity-50"
            >
              {computing ? 'RECOMPUTING…' : 'FILL GAP'}
            </button>
          )}
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

      {computeReport.length > 0 && (
        <ul className="bg-surface-container-low p-space-md rounded-xl border border-amber-400/40 text-xs font-mono text-on-surface-variant space-y-1">
          {computeReport.map((d) => (
            <li key={d} className="flex gap-2">
              <span className="text-amber-400">i</span>
              {d}
            </li>
          ))}
        </ul>
      )}

      {/* 2. RISK & RETURN METRICS — every figure is computed by GET /portfolio/metrics for the
             window shown; a null arrives as a dash, never as a zero. The first four come from the
             stored value series, Win Rate from the trade statement (KAN-52). */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-space-sm">
        <MetricTile
          label="Cumulative Return"
          value={percent(stats?.cumulative_return_pct ?? null)}
          caption={
            stats?.cumulative_return_gbp == null
              ? 'No series'
              : `${signed(stats.cumulative_return_gbp)}£${money(Math.abs(stats.cumulative_return_gbp))} over ${stats.trading_days} days`
          }
          tone={returnTone}
        />
        {/* Backed by per-disposal realised P&L over the statement, with corporate actions
            classified, so a share split cannot count as a winning trade. */}
        <MetricTile
          label="Win Rate"
          value={realised?.win_rate_pct == null ? '—' : `${realised.win_rate_pct.toFixed(1)}%`}
          caption={winRateCaption()}
          tone={
            realised?.win_rate_pct == null
              ? 'text-outline'
              : realised.win_rate_pct >= 50
                ? 'text-primary'
                : 'text-error'
          }
        />
        <MetricTile
          label="Max Drawdown"
          value={stats?.max_drawdown_pct == null ? '—' : `−${stats.max_drawdown_pct.toFixed(1)}%`}
          caption={
            stats?.max_drawdown_pct == null
              ? 'Needs two or more values'
              : 'Worst peak-to-trough fall in window'
          }
          tone={stats?.max_drawdown_pct == null ? 'text-outline' : 'text-error'}
        />
        <MetricTile
          label="Ann. Volatility"
          value={
            stats?.annualised_volatility_pct == null
              ? '—'
              : `${stats.annualised_volatility_pct.toFixed(1)}%`
          }
          caption={
            stats?.annualised_volatility_pct == null
              ? 'Needs three or more values'
              : 'Daily deviation × √252'
          }
          tone={stats?.annualised_volatility_pct == null ? 'text-outline' : 'text-on-surface'}
        />
        {/* Deliberately unavailable rather than a figure: an excess return needs a GBP
            risk-free rate and nothing in the stack supplies one. */}
        <MetricTile
          label="Sharpe Ratio"
          value={stats?.sharpe_ratio == null ? '—' : stats.sharpe_ratio.toFixed(2)}
          caption="Unavailable — no GBP risk-free rate source"
          tone="text-outline"
        />
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
            <button
              type="button"
              onClick={() => setShowBenchmark((on) => !on)}
              title="Overlay an S&P 500 tracker, rebased onto this portfolio's opening value"
              className={`flex items-center gap-1.5 transition-colors ${
                showBenchmark ? 'text-[#64B5F6]' : 'text-outline hover:text-on-surface'
              }`}
            >
              <span
                className={`w-3 border-t border-dotted ${
                  showBenchmark ? 'border-[#64B5F6]' : 'border-outline'
                }`}
              />
              S&P 500 BENCHMARK: {showBenchmark ? 'ON' : 'OFF'}
            </button>
            {response && (
              <span className="text-outline">
                AS OF {new Date(response.computed_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>

        {benchmarkError && showBenchmark && (
          <p className="font-data-mono-sm text-[10px] text-error mb-space-sm">
            Benchmark unavailable: {benchmarkError} — no comparison line is drawn.
          </p>
        )}

        <div className="bg-surface-container-lowest p-space-md rounded-lg border border-surface-container/40">
          {visible.length === 0 ? (
            <div className="h-72 flex flex-col items-center justify-center gap-2 text-center">
              <span className="material-symbols-outlined text-[28px] text-outline">
                {status.state === 'loading' ? 'hourglass_top' : 'show_chart'}
              </span>
              <span className="font-data-mono-sm text-sm text-on-surface-variant">
                {status.state === 'loading'
                  ? 'Loading historical values…'
                  : status.state === 'offline'
                    ? 'Could not load the history series.'
                    : 'No historical values for this portfolio.'}
              </span>
              <span className="font-data-mono-sm text-[10px] text-outline max-w-md">
                {status.state === 'loading'
                  ? 'Reading stored daily portfolio values.'
                  : 'No values are stored in user_portfolio_values.json — nothing is charted until there is a real series.'}
              </span>
            </div>
          ) : (
            <>
              <EquityCurveChart
                points={visible}
                benchmark={
                  showBenchmark && benchmarkPoints
                    ? { symbol: benchmarkPoints.symbol, points: benchmarkPoints.points }
                    : null
                }
              />
              <div className="flex items-center justify-between font-data-mono-sm text-[10px] text-outline pt-1">
                <span>
                  {visible[0].date} → {last.date} • {visible.length} TRADING DAYS
                </span>
                <span className="text-primary font-bold">LATEST: £{money(last.value, 0)}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
