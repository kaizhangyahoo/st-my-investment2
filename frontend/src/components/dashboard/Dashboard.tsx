import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar, WorkspaceTab } from '../layout/Sidebar';
import { TopHeader } from '../layout/TopHeader';
import { IgAnalyticsView } from './IgAnalyticsView';
import { T212View } from '../trading212/T212View';
import { TickerMappingView } from '../tickers/TickerMappingView';
import { PerformanceBlotterView } from './PerformanceBlotterView';
import { UnresolvedSymbolsModal } from '../tickers/UnresolvedSymbolsModal';
import { portfolioApi } from '../../services/api';
import { logger } from '../../services/logger';
import { PortfolioSummary, UnresolvedSymbol, UploadResult, FeedStatus } from '../../types';

const deriveFeedStatus = (data: PortfolioSummary): FeedStatus => {
  const dq = data.data_quality;
  if (!dq) return { state: 'live', detail: [`${data.positions.length} positions priced`] };

  const detail: string[] = [];
  if (dq.fx_fallback) {
    detail.push('FX rates unavailable — non-GBP valuations are estimates, not real quotes');
  }
  if (dq.unpriced_tickers.length) {
    detail.push(
      `No price from any provider: ${dq.unpriced_tickers.join(', ')} — totals are understated`,
    );
  }
  // Group the per-attempt failures by provider so the tooltip names the source, not every ticker.
  const byProvider = new Map<string, string[]>();
  dq.failures.forEach((f) => {
    const key = `${f.provider}: ${f.reason}`;
    byProvider.set(key, [...(byProvider.get(key) ?? []), f.ticker]);
  });
  byProvider.forEach((tickers, key) => detail.push(`${key} (${tickers.join(', ')})`));

  if (dq.degraded) return { state: 'degraded', detail };
  if (detail.length) return { state: 'partial', detail };
  return { state: 'live', detail: [`${data.positions.length} positions priced`] };
};

export const Dashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('ig-csv-analysis');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  // Unresolved names from the latest upload, shown until a fresh summary reports its own.
  const [uploadUnresolved, setUploadUnresolved] = useState<UnresolvedSymbol[] | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [feed, setFeed] = useState<FeedStatus>({ state: 'loading', detail: [] });

  const loadData = async () => {
    setFeed({ state: 'loading', detail: [] });
    try {
      const data = await portfolioApi.getSummary();
      setSummary(data);
      setUploadUnresolved(null);
      setFeed(deriveFeedStatus(data));
    } catch (err: any) {
      // Must not be swallowed: a silent failure is indistinguishable from loading, which is
      // what let sample data sit on screen looking real.
      logger.error('Live portfolio summary unavailable; sample data is on screen', err);
      setFeed({
        state: 'offline',
        detail: [
          `GET /api/v1/trades/summary failed: ${err?.message ?? 'unknown error'}`,
          err?.code === 'ECONNABORTED'
            ? 'Request timed out after 60s — is the backend running?'
            : 'Figures shown are sample data, not your portfolio.',
        ],
      });
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    logger.setView(activeTab);
  }, [activeTab]);

  // Unmapped names send the user straight to Reference Data, where SEC suggestions load
  // automatically. Valuation proceeds meanwhile with those rows excluded; saving a mapping
  // re-runs it via onMappingsChanged.
  const handleUploadComplete = (res: UploadResult) => {
    if (res.unresolved_symbols?.length) {
      setUploadUnresolved(res.unresolved_symbols);
      setNoticeOpen(true);
      setActiveTab('reference-data');
    }
    loadData();
  };

  // Stable identity: Modal re-runs its focus-trap effect whenever onDismiss changes.
  const dismissNotice = useCallback(() => setNoticeOpen(false), []);

  const unresolvedSymbols = uploadUnresolved ?? summary?.unresolved_symbols ?? [];

  const handleResetPanels = async () => {
    setSummary(null);
    try {
      await portfolioApi.reset();
    } catch (err) {
      logger.warn('Reset call failed', err);
    }
    loadData();
  };

  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col font-sans">
      {/* Fixed Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        unresolvedCount={unresolvedSymbols.length}
        feed={feed}
      />

      {/* Top Fixed Header */}
      <TopHeader
        activeTab={activeTab}
        isSidebarCollapsed={isSidebarCollapsed}
        onToggleSidebar={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onResetPanels={handleResetPanels}
        onRefreshData={loadData}
      />

      {/* Main Workspace View Content */}
      <main
        className={`flex-1 pt-20 px-4 sm:px-6 lg:px-8 transition-all duration-300 ${
          isSidebarCollapsed ? 'ml-16' : 'ml-60'
        }`}
      >
        <div className="max-w-[1600px] mx-auto py-2">
          {activeTab === 'ig-csv-analysis' && (
            <IgAnalyticsView
              summary={summary}
              feed={feed}
              onReset={handleResetPanels}
              onUploadComplete={handleUploadComplete}
            />
          )}

          {activeTab === 'trading-212-api' && <T212View />}

          {activeTab === 'reference-data' && (
            <TickerMappingView
              unresolvedSymbols={unresolvedSymbols}
              onMappingsChanged={loadData}
            />
          )}

          {activeTab === 'performance-blotter' && <PerformanceBlotterView />}
        </div>
      </main>

      <UnresolvedSymbolsModal
        open={noticeOpen && unresolvedSymbols.length > 0}
        symbols={unresolvedSymbols}
        onDismiss={dismissNotice}
      />
    </div>
  );
};

export default Dashboard;
