import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { portfolioApi } from '../../services/api';
import { PortfolioSummary, Position } from '../../types';

interface IgAnalyticsViewProps {
  summary: PortfolioSummary | null;
  onRefresh: () => void;
  onReset: () => void;
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

const SAMPLE_TRADE_ACTIVITY = [
  { qty: 40, fill: '$128.10', value: '£3,959.81', date: '2026-10-24', time: '14:22:04', activity: 'BUY', market: 'NVIDIA Corp (NVDA)' },
  { qty: 15, fill: '$938.50', value: '£10,878.02', date: '2026-10-18', time: '15:10:33', activity: 'BUY', market: 'Lam Research Corp (LRCX)' },
  { qty: 25, fill: '$130.40', value: '£2,519.32', date: '2026-10-12', time: '18:04:12', activity: 'SELL', market: '3M Company (MMM)' },
  { qty: 100, fill: '$53.90', value: '£4,165.38', date: '2026-09-28', time: '13:45:00', activity: 'BUY', market: 'Lumentum Holdings (LITE)' },
  { qty: 30, fill: '$224.50', value: '£5,204.80', date: '2026-09-14', time: '16:01:29', activity: 'BUY', market: 'Apple Inc (AAPL)' },
  { qty: 10, fill: '$592.10', value: '£4,575.73', date: '2026-09-02', time: '19:15:40', activity: 'SELL', market: 'MSCI Inc (MSCI)' },
];

export const IgAnalyticsView: React.FC<IgAnalyticsViewProps> = ({
  summary,
  onRefresh,
  onReset,
}) => {
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTicker, setSelectedTicker] = useState('MMM');
  const [activityFilter, setActivityFilter] = useState<'ALL' | 'BUYS' | 'SELLS'>('ALL');

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
        onRefresh();
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

  // Calculate or fallback data
  const hasLivePositions = summary && summary.positions && summary.positions.length > 0;
  const positions = hasLivePositions ? summary.positions : SAMPLE_POSITIONS;

  const totalValue = hasLivePositions
    ? summary.total_market_value_gbp
    : positions.reduce((acc, p) => acc + p.market_value_gbp, 0);

  const totalCost = hasLivePositions
    ? summary.total_invested_cash
    : totalValue - positions.reduce((acc, p) => acc + p.pnl_gbp, 0);

  const totalPnl = hasLivePositions
    ? summary.total_pnl_gbp
    : positions.reduce((acc, p) => acc + p.pnl_gbp, 0);

  const pnlPercent = totalCost > 0 ? ((totalPnl / totalCost) * 100).toFixed(1) : '16.9';

  // Filtered positions
  const filteredPositions = positions.filter(
    (p) =>
      p.ticker.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.market.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Filtered trade activity
  const filteredActivity = SAMPLE_TRADE_ACTIVITY.filter((item) => {
    if (activityFilter === 'BUYS') return item.activity === 'BUY';
    if (activityFilter === 'SELLS') return item.activity === 'SELL';
    return true;
  });

  const selectedHolding = positions.find((p) => p.ticker === selectedTicker) || positions[0];

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
              className={`border border-dashed rounded-lg p-space-md flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
                isDragActive
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
          </div>

          {/* Active File Status Bar */}
          <div className="flex items-center justify-between pt-3 mt-3 border-t border-surface-container/40 text-on-surface-variant">
            <div className="flex items-center gap-1.5 truncate max-w-[200px]">
              <span className="material-symbols-outlined text-[15px] text-secondary">description</span>
              <span className="font-data-mono-sm text-data-mono-sm text-secondary truncate">
                {uploadedFiles.length > 0 ? uploadedFiles[0] : 'sample_trade_ledger_2026.csv'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-label-caps text-label-caps text-outline">PARSER: IG</span>
              <button
                type="button"
                onClick={onReset}
                title="Reset panels"
                className="p-1 rounded hover:bg-surface-container text-outline hover:text-tertiary transition-colors"
              >
                <span className="material-symbols-outlined text-[14px]">close</span>
              </button>
            </div>
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
              BASE: GBP (£) • SPOT 15:26 BST
            </span>
          </div>

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
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-primary">
                <span className="material-symbols-outlined text-[14px]">trending_up</span>
                <span>+£14,920.40 today</span>
              </div>
            </div>

            {/* Cash Available */}
            <div className="p-space-sm rounded-lg bg-surface-container-lowest border border-surface-container/40 flex flex-col justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Cash Available (Uninvested)
              </span>
              <span className="font-data-mono-lg text-data-mono-lg text-on-surface tracking-tight my-1 font-semibold">
                £48,290.15
              </span>
              <div className="flex items-center gap-1 font-data-mono-sm text-data-mono-sm text-secondary">
                <span className="material-symbols-outlined text-[14px]">info</span>
                <span>7.4% Liquidity buffer</span>
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
                <span>Net Deposits £520.4k</span>
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
                <span>+{pnlPercent}% Portfolio ROI</span>
              </div>
            </div>
          </div>

          {/* Currency Allocation Pill Strip */}
          <div className="mt-space-xs pt-space-xs border-t border-surface-container/30 flex flex-wrap items-center justify-between text-xs font-mono">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
              Currency Distribution:
            </span>
            <div className="flex items-center gap-space-md">
              <span className="px-2 py-0.5 rounded bg-surface-container text-secondary font-data-mono-sm">
                GBP: 42.1% (£274.9k)
              </span>
              <span className="px-2 py-0.5 rounded bg-surface-container text-primary font-data-mono-sm">
                USD: 49.3% ($408.2k)
              </span>
              <span className="px-2 py-0.5 rounded bg-surface-container text-tertiary-fixed font-data-mono-sm">
                EUR: 8.6% (€64.1k)
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MIDDLE SECTION 1: Holdings Matrix & Currency/Sector Donut
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Comprehensive Holdings Table (8 Cols) */}
        <div className="xl:col-span-8 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col">
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
                      className={`hover:bg-surface-container-high/60 cursor-pointer transition-colors ${
                        isSelected ? 'bg-surface-container-high/90 shadow-[inset_2px_0_0_0_#4edea3]' : ''
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
                          className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${
                            isPositive
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'bg-error/10 text-error border border-error/20'
                          }`}
                        >
                          {isPositive ? '+' : ''}£{p.pnl_gbp.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-2.5 px-space-sm text-center">
                        <svg className="w-14 h-4 mx-auto" viewBox="0 0 60 16">
                          <path
                            d={
                              isPositive
                                ? 'M2 13 L15 11 L28 14 L42 5 L58 3'
                                : 'M2 4 L16 6 L30 3 L44 12 L58 14'
                            }
                            fill="none"
                            stroke={isPositive ? '#4edea3' : '#ffb4ab'}
                            strokeWidth="1.5"
                            strokeLinecap="round"
                          />
                        </svg>
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
          </div>
        </div>

        {/* Currency & Sector Allocation (4 Cols) */}
        <div className="xl:col-span-4 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs mb-space-sm border-b border-surface-container/40">
              <span className="font-headline-md text-headline-md text-on-surface font-semibold flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[18px] text-secondary">donut_large</span>
                Currency & Asset Allocation
              </span>
              <span className="font-label-caps text-label-caps text-outline">SPOT FX</span>
            </div>

            {/* SVG Donut Chart */}
            <div className="flex items-center justify-center py-4">
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
                  {/* USD Slice: 49.3% */}
                  <path
                    className="text-primary"
                    strokeDasharray="49.3, 100"
                    strokeWidth="4.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  {/* GBP Slice: 42.1% */}
                  <path
                    className="text-secondary"
                    strokeDasharray="42.1, 100"
                    strokeDashoffset="-49.3"
                    strokeWidth="4.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  {/* EUR Slice: 8.6% */}
                  <path
                    className="text-tertiary-fixed"
                    strokeDasharray="8.6, 100"
                    strokeDashoffset="-91.4"
                    strokeWidth="4.5"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="font-data-mono-lg text-data-mono-lg font-bold text-on-surface">100%</span>
                  <span className="font-label-caps text-[9px] text-outline uppercase">Allocated</span>
                </div>
              </div>
            </div>

            {/* Currency Breakdown Legend */}
            <div className="space-y-2 mt-2">
              <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                  <span className="font-body-sm text-xs text-on-surface font-medium">US Dollar (USD)</span>
                </div>
                <span className="font-data-mono-sm text-xs text-on-surface">49.3% • £321.9k</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-secondary" />
                  <span className="font-body-sm text-xs text-on-surface font-medium">British Pound (GBP)</span>
                </div>
                <span className="font-data-mono-sm text-xs text-on-surface">42.1% • £274.9k</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-surface-container/30">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-tertiary-fixed" />
                  <span className="font-body-sm text-xs text-on-surface font-medium">Euro (EUR)</span>
                </div>
                <span className="font-data-mono-sm text-xs text-on-surface">8.6% • £56.2k</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-surface-container/40 text-[11px] text-outline font-mono flex items-center justify-between">
            <span>RISK HEDGE: 0% SYNTHETIC</span>
            <span className="text-primary">NO LIQUIDITY LOCK</span>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MIDDLE SECTION 2: Single Instrument Inspector (Interactive)
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-space-sm border-b border-surface-container/40 mb-space-sm">
          <div className="flex items-center gap-space-sm">
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
              value={selectedTicker}
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
            <span className="font-label-caps text-[10px] text-outline block">AVG EXECUTION BASIS</span>
            <span className="font-data-mono-lg text-sm text-on-surface font-semibold">
              ${(selectedHolding.current_price ? selectedHolding.current_price * 0.88 : 112).toFixed(2)}
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

            {/* Chart SVG */}
            <svg className="w-full h-56" viewBox="0 0 900 240">
              <defs>
                <linearGradient id="priceGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#4edea3" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#4edea3" stopOpacity="0.0" />
                </linearGradient>
              </defs>
              {/* Gridlines */}
              <line x1="40" y1="40" x2="880" y2="40" stroke="#1c2028" strokeDasharray="3,3" />
              <line x1="40" y1="100" x2="880" y2="100" stroke="#1c2028" strokeDasharray="3,3" />
              <line x1="40" y1="160" x2="880" y2="160" stroke="#1c2028" strokeDasharray="3,3" />
              <line x1="40" y1="210" x2="880" y2="210" stroke="#1c2028" />

              {/* Area path */}
              <path
                d="M 40 180 Q 150 160, 240 135 T 450 120 T 650 75 T 880 50 L 880 210 L 40 210 Z"
                fill="url(#priceGradient)"
              />
              {/* Line vector */}
              <path
                d="M 40 180 Q 150 160, 240 135 T 450 120 T 650 75 T 880 50"
                fill="none"
                stroke="#4edea3"
                strokeWidth="2.5"
                strokeLinecap="round"
              />

              {/* BUY Marker 1 */}
              <circle cx="240" cy="135" r="5" fill="#4edea3" />
              <polygon points="240,118 235,128 245,128" fill="#4edea3" />
              <text x="240" y="112" fill="#4edea3" fontSize="10" textAnchor="middle" fontFamily="monospace">
                BUY +40
              </text>

              {/* BUY Marker 2 */}
              <circle cx="530" cy="98" r="5" fill="#4edea3" />
              <polygon points="530,81 525,91 535,91" fill="#4edea3" />
              <text x="530" y="75" fill="#4edea3" fontSize="10" textAnchor="middle" fontFamily="monospace">
                BUY +25
              </text>

              {/* SELL Marker */}
              <circle cx="700" cy="68" r="5" fill="#ffb4ab" />
              <polygon points="700,85 695,75 705,75" fill="#ffb4ab" />
              <text x="700" y="98" fill="#ffb4ab" fontSize="10" textAnchor="middle" fontFamily="monospace">
                SELL -15
              </text>
            </svg>
          </div>

          {/* Single Instrument Trade Fills (4 cols) */}
          <div className="lg:col-span-4 bg-surface-container-lowest p-space-sm rounded-lg border border-surface-container/40 flex flex-col justify-between">
            <div>
              <span className="font-label-caps text-label-caps text-outline block mb-2 uppercase">
                {selectedHolding.ticker} Execution Audit
              </span>
              <div className="space-y-2">
                <div className="p-2 rounded bg-surface-container-low border border-surface-container/30 flex items-center justify-between text-xs font-mono">
                  <div>
                    <span className="text-primary font-bold">BUY 40 shs</span>
                    <span className="text-outline block text-[10px]">2026-09-15 14:10</span>
                  </div>
                  <div className="text-right">
                    <span className="text-on-surface font-semibold">$118.40</span>
                    <span className="text-outline block text-[10px]">Settled: £3,660.10</span>
                  </div>
                </div>

                <div className="p-2 rounded bg-surface-container-low border border-surface-container/30 flex items-center justify-between text-xs font-mono">
                  <div>
                    <span className="text-primary font-bold">BUY 25 shs</span>
                    <span className="text-outline block text-[10px]">2026-08-02 16:35</span>
                  </div>
                  <div className="text-right">
                    <span className="text-on-surface font-semibold">$122.10</span>
                    <span className="text-outline block text-[10px]">Settled: £2,402.15</span>
                  </div>
                </div>

                <div className="p-2 rounded bg-surface-container-low border border-surface-container/30 flex items-center justify-between text-xs font-mono">
                  <div>
                    <span className="text-tertiary font-bold">SELL 15 shs</span>
                    <span className="text-outline block text-[10px]">2026-07-11 15:02</span>
                  </div>
                  <div className="text-right">
                    <span className="text-on-surface font-semibold">$129.80</span>
                    <span className="text-outline block text-[10px]">Proceeds: £1,520.40</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-2 mt-2 border-t border-surface-container/30 flex items-center justify-between text-[11px] font-mono text-outline">
              <span>BROKER: IG BROKERAGE</span>
              <span className="text-secondary">ACCOUNT #QX2B3</span>
            </div>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MIDDLE SECTION 3: Trade History This Quarter
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
          <div className="flex items-center gap-space-sm">
            <span className="material-symbols-outlined text-[18px] text-secondary">history</span>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Trade Activity Ledger (Recent Quarters)
            </span>
          </div>

          {/* Filter Pills */}
          <div className="flex items-center gap-1 bg-surface-container-lowest p-1 rounded border border-surface-container font-label-caps text-label-caps">
            <button
              type="button"
              onClick={() => setActivityFilter('ALL')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activityFilter === 'ALL'
                  ? 'bg-surface-container-high text-primary font-bold'
                  : 'text-outline hover:text-on-surface'
              }`}
            >
              ALL ({SAMPLE_TRADE_ACTIVITY.length})
            </button>
            <button
              type="button"
              onClick={() => setActivityFilter('BUYS')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activityFilter === 'BUYS'
                  ? 'bg-surface-container-high text-primary font-bold'
                  : 'text-outline hover:text-on-surface'
              }`}
            >
              BUYS (4)
            </button>
            <button
              type="button"
              onClick={() => setActivityFilter('SELLS')}
              className={`px-2.5 py-1 rounded transition-colors ${
                activityFilter === 'SELLS'
                  ? 'bg-surface-container-high text-tertiary font-bold'
                  : 'text-outline hover:text-on-surface'
              }`}
            >
              SELLS (2)
            </button>
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
              {filteredActivity.map((act, idx) => (
                <tr key={idx} className="hover:bg-surface-container-high/40">
                  <td className="py-2 px-space-sm">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        act.activity === 'BUY'
                          ? 'bg-primary/10 text-primary border border-primary/20'
                          : 'bg-error/10 text-error border border-error/20'
                      }`}
                    >
                      {act.activity}
                    </span>
                  </td>
                  <td className="py-2 px-space-sm text-on-surface font-medium">
                    {act.market}
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
              ))}
            </tbody>
          </table>
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
          <div className="p-3 rounded bg-surface-container-lowest border border-surface-container/30">
            <span className="font-label-caps text-[10px] text-outline block">DIVIDENDS RECEIVED</span>
            <span className="font-data-mono-lg text-sm text-primary font-bold block mt-1">+£12,480.50</span>
            <span className="font-body-sm text-[10px] text-on-surface-variant">42 payments</span>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border border-surface-container/30">
            <span className="font-label-caps text-[10px] text-outline block">CASH INTEREST</span>
            <span className="font-data-mono-lg text-sm text-secondary font-bold block mt-1">+£1,840.10</span>
            <span className="font-body-sm text-[10px] text-on-surface-variant">Platform yield</span>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border border-surface-container/30">
            <span className="font-label-caps text-[10px] text-outline block">DEALING COMMISSIONS</span>
            <span className="font-data-mono-lg text-sm text-error font-bold block mt-1">-£420.00</span>
            <span className="font-body-sm text-[10px] text-on-surface-variant">Broker execution</span>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border border-surface-container/30">
            <span className="font-label-caps text-[10px] text-outline block">STAMP DUTY (SDRT)</span>
            <span className="font-data-mono-lg text-sm text-error font-bold block mt-1">-£312.40</span>
            <span className="font-body-sm text-[10px] text-on-surface-variant">UK 0.5% levy</span>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border border-primary/20 bg-primary/5">
            <span className="font-label-caps text-[10px] text-primary block">NET CASH REINVESTED</span>
            <span className="font-data-mono-lg text-sm text-primary font-bold block mt-1">+£13,588.20</span>
            <span className="font-body-sm text-[10px] text-on-surface-variant">Compound return</span>
          </div>
        </div>
      </div>
    </div>
  );
};
