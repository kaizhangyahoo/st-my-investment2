import React from 'react';
import { WorkspaceTab } from './Sidebar';

interface TopHeaderProps {
  activeTab: WorkspaceTab;
  isSidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onResetPanels?: () => void;
  onRefreshData?: () => void;
}

export const TopHeader: React.FC<TopHeaderProps> = ({
  activeTab,
  isSidebarCollapsed,
  onToggleSidebar,
  onResetPanels,
  onRefreshData,
}) => {
  const tabTitles: Record<WorkspaceTab, string> = {
    'ig-csv-analysis': 'IG Broker Statement & Execution Blotter',
    'trading-212-api': 'Trading 212 Pure REST API Engine',
    'reference-data': 'Reference Data & Symbology Reconciliation',
    'performance-blotter': 'Consolidated Performance & Benchmark Analytics',
  };

  return (
    <header
      className={`fixed top-0 right-0 h-16 bg-surface/90 backdrop-blur-xl z-40 flex items-center justify-between px-space-lg shadow-[0_1px_8px_rgba(0,0,0,0.3)] border-b border-surface-container transition-all duration-300 ${
        isSidebarCollapsed ? 'left-16' : 'left-60'
      }`}
    >
      {/* Left: Sidebar Toggle + Title */}
      <div className="flex items-center gap-space-md">
        <button
          onClick={onToggleSidebar}
          type="button"
          title="Toggle sidebar"
          className="flex items-center gap-1.5 px-space-sm py-1.5 rounded bg-surface-container-low hover:bg-surface-container text-on-surface transition-colors border border-surface-container/80 text-xs font-mono font-medium"
        >
          <span className="material-symbols-outlined text-[18px] text-primary">view_sidebar</span>
          <span className="hidden sm:inline font-label-caps">SIDEBAR</span>
        </button>

        <div className="h-4 w-px bg-surface-container hidden sm:block" />

        <div className="flex flex-col">
          <span className="font-headline-md text-headline-md text-on-surface leading-tight font-semibold flex items-center gap-2">
            {tabTitles[activeTab]}
          </span>
          <span className="font-label-caps text-[10px] text-outline tracking-wider uppercase">
            Institutional Portfolio Telemetry • Terminal v2.4
          </span>
        </div>
      </div>

      {/* Right Controls: Dev Mode, Actions */}
      <div className="flex items-center gap-space-sm">
        {/* Local Dev Mode Badge */}
        <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-container-high border border-primary/30 text-primary font-label-caps text-label-caps">
          <span className="material-symbols-outlined text-[13px] text-primary">lock_open</span>
          <span className="hidden md:inline">DEV MODE (LOGIN BYPASSED)</span>
        </div>

        {/* Refresh Data */}
        {onRefreshData && (
          <button
            onClick={onRefreshData}
            type="button"
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-surface-container-low hover:bg-surface-container text-on-surface-variant hover:text-on-surface border border-surface-container font-label-caps text-label-caps transition-colors"
            title="Refresh calculations and live quotes"
          >
            <span className="material-symbols-outlined text-[15px] text-secondary">sync</span>
            <span className="hidden sm:inline">SYNC</span>
          </button>
        )}

        {/* Reset Panels */}
        {onResetPanels && (
          <button
            onClick={onResetPanels}
            type="button"
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-tertiary-container/20 hover:bg-tertiary-container/30 text-tertiary border border-tertiary/30 font-label-caps text-label-caps transition-colors"
            title="Clear in-memory cache and reset views"
          >
            <span className="material-symbols-outlined text-[15px]">restart_alt</span>
            <span className="hidden sm:inline">RESET</span>
          </button>
        )}
      </div>
    </header>
  );
};
