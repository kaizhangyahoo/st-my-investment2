import React, { useState, useEffect } from 'react';
import { portfolioApi } from '../../services/api';
import { PortfolioHistoryPoint } from '../../types';

// Fallback time series data matching Stitch design
const SAMPLE_HISTORY_POINTS: PortfolioHistoryPoint[] = [
  { date: '2024-02-08', value: 96563.45 },
  { date: '2024-02-15', value: 97313.52 },
  { date: '2024-02-23', value: 96466.34 },
  { date: '2024-03-01', value: 98288.91 },
  { date: '2024-03-08', value: 99090.62 },
  { date: '2024-03-15', value: 101240.10 },
  { date: '2024-03-22', value: 102450.80 },
  { date: '2024-03-29', value: 104820.30 },
  { date: '2024-04-05', value: 103910.40 },
  { date: '2024-04-12', value: 106400.00 },
  { date: '2024-04-19', value: 108920.50 },
  { date: '2024-04-26', value: 111450.80 },
  { date: '2024-05-03', value: 114200.10 },
  { date: '2024-05-10', value: 117540.30 },
  { date: '2024-05-17', value: 119840.00 },
  { date: '2024-05-24', value: 122410.60 },
  { date: '2024-05-31', value: 125910.20 },
];

export const PerformanceBlotterView: React.FC = () => {
  const [history, setHistory] = useState<PortfolioHistoryPoint[]>([]);
  const [timeframe, setTimeframe] = useState<'1M' | '3M' | '6M' | '1Y' | 'ALL'>('ALL');
  const [showBenchmark, setShowBenchmark] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await portfolioApi.getHistory('QX2B3');
        if (data && data.length > 0) {
          setHistory(data);
        } else {
          setHistory(SAMPLE_HISTORY_POINTS);
        }
      } catch {
        setHistory(SAMPLE_HISTORY_POINTS);
      }
    };
    load();
  }, []);

  const displayHistory = history.length > 0 ? history : SAMPLE_HISTORY_POINTS;
  const initialValue = displayHistory[0]?.value || 100000;
  const latestValue = displayHistory[displayHistory.length - 1]?.value || 125910;
  const absoluteReturn = latestValue - initialValue;
  const percentReturn = ((absoluteReturn / initialValue) * 100).toFixed(1);

  return (
    <div className="space-y-space-lg pb-16">
      {/* ─────────────────────────────────────────────────────────────
          1. HEADER TELEMETRY STRIP
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-space-md">
        <div className="flex items-center gap-space-sm">
          <span className="material-symbols-outlined text-[20px] text-primary">candlestick_chart</span>
          <div>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Performance Blotter & Historical Alpha Telemetry
            </span>
            <span className="font-label-caps text-[10px] text-outline block">
              PORTFOLIO HISTORY OVER TIME • S&P 500 BENCHMARK RELATIVE RETURN
            </span>
          </div>
        </div>

        {/* Range Selector & Benchmark Toggle */}
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            onClick={() => setShowBenchmark(!showBenchmark)}
            className={`px-2.5 py-1 rounded text-xs font-mono font-medium border transition-colors ${
              showBenchmark
                ? 'bg-secondary/20 text-secondary border-secondary/40'
                : 'bg-surface-container text-outline border-surface-container'
            }`}
          >
            S&P 500 BENCHMARK: {showBenchmark ? 'ON' : 'OFF'}
          </button>

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

      {/* ─────────────────────────────────────────────────────────────
          2. RISK & RETURN METRICS CARDS
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-space-sm">
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Cumulative Return</span>
          <span className="font-data-mono-lg text-sm text-primary font-bold my-1 block">
            +{percentReturn}%
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">
            +£{absoluteReturn.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Sharpe Ratio</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1 block">
            1.84
          </span>
          <span className="font-data-mono-sm text-[10px] text-secondary">Risk-Adjusted Alpha</span>
        </div>

        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Max Drawdown</span>
          <span className="font-data-mono-lg text-sm text-error font-bold my-1 block">
            -4.2%
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">Q1 Dip Recovered</span>
        </div>

        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Ann. Volatility</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1 block">
            11.2%
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">Low Beta (0.78)</span>
        </div>

        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Win Rate</span>
          <span className="font-data-mono-lg text-sm text-primary font-bold my-1 block">
            68.4%
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">28 of 41 Positions</span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          3. TIME SERIES EQUITY CURVE & BENCHMARK SVG CHART
      ───────────────────────────────────────────────────────────── */}
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
              KAI FAMILY OFFICE PORTFOLIO
            </span>
            {showBenchmark && (
              <span className="flex items-center gap-1.5 text-secondary">
                <span className="w-3 h-0.5 bg-secondary border-dashed" />
                S&P 500 REINVESTED
              </span>
            )}
          </div>
        </div>

        {/* SVG Equity Chart */}
        <div className="bg-surface-container-lowest p-space-md rounded-lg border border-surface-container/40">
          <svg className="w-full h-72" viewBox="0 0 900 240">
            <defs>
              <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#4edea3" stopOpacity="0.25" />
                <stop offset="100%" stopColor="#4edea3" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Gridlines */}
            <line x1="40" y1="40" x2="880" y2="40" stroke="#1c2028" strokeDasharray="3,3" />
            <line x1="40" y1="90" x2="880" y2="90" stroke="#1c2028" strokeDasharray="3,3" />
            <line x1="40" y1="140" x2="880" y2="140" stroke="#1c2028" strokeDasharray="3,3" />
            <line x1="40" y1="190" x2="880" y2="190" stroke="#1c2028" strokeDasharray="3,3" />
            <line x1="40" y1="210" x2="880" y2="210" stroke="#262a33" />

            {/* Axis Y Values */}
            <text x="35" y="44" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">£130k</text>
            <text x="35" y="94" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">£115k</text>
            <text x="35" y="144" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">£105k</text>
            <text x="35" y="194" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">£95k</text>

            {/* Equity Curve Area */}
            <path
              d="M 50 190 Q 180 180, 280 160 T 500 120 T 700 80 T 870 45 L 870 210 L 50 210 Z"
              fill="url(#equityGradient)"
            />

            {/* Primary Equity Line */}
            <path
              d="M 50 190 Q 180 180, 280 160 T 500 120 T 700 80 T 870 45"
              fill="none"
              stroke="#4edea3"
              strokeWidth="2.5"
              strokeLinecap="round"
            />

            {/* Benchmark Line */}
            {showBenchmark && (
              <path
                d="M 50 190 Q 200 185, 320 170 T 520 145 T 720 115 T 870 95"
                fill="none"
                stroke="#93ccff"
                strokeWidth="1.5"
                strokeDasharray="5,5"
              />
            )}

            {/* Interactive Target Ring at Peak */}
            <circle cx="870" cy="45" r="5" fill="#4edea3" />
            <circle cx="870" cy="45" r="9" fill="none" stroke="#4edea3" strokeWidth="1.5" opacity="0.5" />
            <text x="860" y="30" fill="#4edea3" fontSize="11" textAnchor="end" fontFamily="monospace" fontWeight="bold">
              LATEST: £{latestValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </text>

            {/* X Axis Time Labels */}
            <text x="50" y="225" fill="#86948a" fontSize="10" fontFamily="monospace">2024-02</text>
            <text x="250" y="225" fill="#86948a" fontSize="10" fontFamily="monospace">2024-03</text>
            <text x="460" y="225" fill="#86948a" fontSize="10" fontFamily="monospace">2024-04</text>
            <text x="670" y="225" fill="#86948a" fontSize="10" fontFamily="monospace">2024-05</text>
            <text x="870" y="225" fill="#86948a" fontSize="10" textAnchor="end" fontFamily="monospace">PRESENT</text>
          </svg>
        </div>
      </div>
    </div>
  );
};
