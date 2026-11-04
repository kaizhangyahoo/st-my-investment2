import React, { useState, useEffect } from 'react';
import { Navbar } from '../layout/Navbar';
import { MetricCard } from '../common/MetricCard';
import { FileUploader } from '../trades/FileUploader';
import { PositionsTable } from './PositionsTable';
import { CurrencyBreakdownPie } from './CurrencyBreakdownPie';
import { MappingEditorTable } from '../tickers/MappingEditorTable';
import { T212Section } from '../trading212/T212Section';
import { portfolioApi } from '../../services/api';
import { PortfolioSummary } from '../../types';


export const Dashboard: React.FC = () => {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [activeTab, setActiveTab] = useState<'holdings' | 'tickers' | 'trading212'>('holdings');

  const loadData = async () => {
    try {
      const data = await portfolioApi.getSummary();
      setSummary(data);
    } catch (err) {
      console.error('Failed to load portfolio summary', err);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const totalValue = summary?.total_market_value_gbp || 0;
  const totalCost = summary?.total_invested_cash || 0;
  const totalPnl = summary?.total_pnl_gbp || 0;
  const pnlPercent = totalCost > 0 ? ((totalPnl / totalCost) * 100).toFixed(1) + '%' : undefined;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 pb-12">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 space-y-6">
        {/* KPI Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <MetricCard
            label="Total Portfolio Value"
            value={`£${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          />
          <MetricCard
            label="Total Capital Invested"
            value={`£${totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          />
          <MetricCard
            label="Unrealized Profit & Loss"
            value={`£${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            delta={pnlPercent}
            isPositive={totalPnl >= 0}
          />
        </div>

        {/* Upload Zone */}
        <FileUploader onUploadSuccess={loadData} />

        {/* Tab Navigation */}
        <div className="flex space-x-2 border-b border-slate-200 dark:border-slate-800 pb-2">
          <button
            onClick={() => setActiveTab('holdings')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
              activeTab === 'holdings'
                ? 'bg-blue-600 text-white'
                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            Holdings & Allocation
          </button>
          <button
            onClick={() => setActiveTab('tickers')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
              activeTab === 'tickers'
                ? 'bg-blue-600 text-white'
                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            Ticker Mapping Editor
          </button>
          <button
            onClick={() => setActiveTab('trading212')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
              activeTab === 'trading212'
                ? 'bg-blue-600 text-white'
                : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            Trading 212 API
          </button>
        </div>

        {/* Active Tab Content */}
        {activeTab === 'holdings' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <PositionsTable positions={summary?.positions || []} />
            </div>
            <div>
              <CurrencyBreakdownPie allocation={summary?.currency_allocation} />
            </div>
          </div>
        )}

        {activeTab === 'tickers' && <MappingEditorTable />}

        {activeTab === 'trading212' && <T212Section />}
      </main>
    </div>
  );
};
