import React, { useState, useEffect } from 'react';
import { Sidebar, WorkspaceTab } from '../layout/Sidebar';
import { TopHeader } from '../layout/TopHeader';
import { IgAnalyticsView } from './IgAnalyticsView';
import { T212View } from '../trading212/T212View';
import { TickerMappingView } from '../tickers/TickerMappingView';
import { PerformanceBlotterView } from './PerformanceBlotterView';
import { portfolioApi } from '../../services/api';
import { PortfolioSummary } from '../../types';

export const Dashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('ig-csv-analysis');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);

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

  const handleResetPanels = () => {
    setSummary(null);
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
              onRefresh={loadData}
              onReset={handleResetPanels}
            />
          )}

          {activeTab === 'trading-212-api' && <T212View />}

          {activeTab === 'reference-data' && <TickerMappingView />}

          {activeTab === 'performance-blotter' && <PerformanceBlotterView />}
        </div>
      </main>
    </div>
  );
};

export default Dashboard;
