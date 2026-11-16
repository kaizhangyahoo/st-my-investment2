import React, { useState, useEffect } from 'react';
import { Sidebar, WorkspaceTab } from '../layout/Sidebar';
import { TopHeader } from '../layout/TopHeader';
import { IgAnalyticsView } from './IgAnalyticsView';
import { T212View } from '../trading212/T212View';
import { TickerMappingView } from '../tickers/TickerMappingView';
import { PerformanceBlotterView } from './PerformanceBlotterView';
import { UnresolvedSymbolsModal } from '../tickers/UnresolvedSymbolsModal';
import { portfolioApi } from '../../services/api';
import { PortfolioSummary, UnresolvedSymbol, UploadResult } from '../../types';

export const Dashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('ig-csv-analysis');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [gateSymbols, setGateSymbols] = useState<UnresolvedSymbol[]>([]);

  const loadData = async () => {
    try {
      const data = await portfolioApi.getSummary();
      setSummary(data);
    } catch (err) {
      console.warn('Backend not serving live summary; falling back to terminal baseline', err);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Gate the valuation behind mapping review: hold the summary back until the
  // user has either resolved the unmapped names or explicitly skipped them.
  const handleUploadComplete = (res: UploadResult) => {
    if (res.unresolved_symbols?.length) {
      setGateSymbols(res.unresolved_symbols);
      return;
    }
    loadData();
  };

  const handleGateResolved = () => {
    setGateSymbols([]);
    loadData();
  };

  const handleGateSkipped = () => {
    setGateSymbols([]);
    loadData();
  };

  const handleResetPanels = async () => {
    setSummary(null);
    try {
      await portfolioApi.reset();
    } catch (err) {
      console.warn('Reset call failed:', err);
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
        unresolvedCount={summary?.unresolved_symbols?.length ?? 0}
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
              onReset={handleResetPanels}
              onUploadComplete={handleUploadComplete}
            />
          )}

          {activeTab === 'trading-212-api' && <T212View />}

          {activeTab === 'reference-data' && (
            <TickerMappingView
              unresolvedSymbols={summary?.unresolved_symbols ?? []}
              onMappingsChanged={loadData}
            />
          )}

          {activeTab === 'performance-blotter' && <PerformanceBlotterView />}
        </div>
      </main>

      <UnresolvedSymbolsModal
        open={gateSymbols.length > 0}
        symbols={gateSymbols}
        onResolved={handleGateResolved}
        onSkip={handleGateSkipped}
      />
    </div>
  );
};

export default Dashboard;
