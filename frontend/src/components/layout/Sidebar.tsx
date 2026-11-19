import React from 'react';
import { FeedState, FeedStatus } from '../../types';

export type WorkspaceTab = 'ig-csv-analysis' | 'trading-212-api' | 'reference-data' | 'performance-blotter';

interface SidebarProps {
  activeTab: WorkspaceTab;
  onSelectTab: (tab: WorkspaceTab) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  unresolvedCount?: number;
  feed?: FeedStatus;
}

const FEED_PRESENTATION: Record<FeedState, { label: string; text: string; dot: string; pulse: boolean }> = {
  loading: { label: 'SYNCING…', text: 'text-amber-400', dot: 'bg-amber-400', pulse: true },
  live: { label: 'LIVE_SYNC', text: 'text-primary', dot: 'bg-primary', pulse: true },
  partial: { label: 'PARTIAL', text: 'text-amber-400', dot: 'bg-amber-400', pulse: false },
  degraded: { label: 'DEGRADED', text: 'text-error', dot: 'bg-error', pulse: true },
  offline: { label: 'FEED_ERROR', text: 'text-error', dot: 'bg-error', pulse: true },
};

const FEED_HEADLINE: Record<FeedState, string> = {
  loading: 'Fetching live prices — figures shown are sample data',
  live: 'All positions priced from live market data',
  partial: 'Priced via fallback provider',
  degraded: 'Live data incomplete — figures are unreliable',
  offline: 'Cannot reach the backend',
};

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onSelectTab,
  isCollapsed,
  onToggleCollapse,
  unresolvedCount = 0,
  feed = { state: 'loading', detail: [] },
}) => {
  const presentation = FEED_PRESENTATION[feed.state];
  const isBad = feed.state === 'degraded' || feed.state === 'offline';
  return (
    <aside
      className={`fixed left-0 top-0 h-full bg-surface-container-lowest z-50 flex flex-col justify-between shadow-[0_1px_8px_rgba(0,0,0,0.2)] transition-all duration-300 border-r border-surface-container ${
        isCollapsed ? 'w-16' : 'w-60'
      }`}
    >
      <div className="flex flex-col">
        {/* Brand Header */}
        <div className="h-16 px-space-lg flex items-center justify-between bg-surface-container-low border-b border-surface-container/60">
          <div className="flex items-center gap-space-sm overflow-hidden">
            <div className="w-8 h-8 rounded bg-primary-container flex-shrink-0 flex items-center justify-center font-headline-md font-bold text-on-primary-container shadow-sm">
              K
            </div>
            {!isCollapsed && (
              <div className="flex flex-col truncate">
                <span className="font-headline-md text-headline-md tracking-tight text-on-surface font-semibold leading-tight">
                  KAI
                </span>
                <span className="font-label-caps text-[10px] text-on-surface-variant uppercase tracking-wider truncate">
                  Family Office Investment
                </span>
              </div>
            )}
          </div>
          <button
            onClick={onToggleCollapse}
            type="button"
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-1 rounded hover:bg-surface-container text-outline hover:text-on-surface transition-colors flex items-center justify-center"
          >
            <span className="material-symbols-outlined text-[18px]">
              {isCollapsed ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left'}
            </span>
          </button>
        </div>

        {/* Workspaces Section */}
        <div className="px-space-md pt-space-lg pb-space-xs">
          {!isCollapsed && (
            <span className="px-space-sm font-label-caps text-label-caps uppercase text-outline tracking-wider">
              Analytics Workspaces
            </span>
          )}
        </div>

        <nav className="flex flex-col gap-space-xs px-space-md">
          {/* IG CSV Analysis */}
          <button
            onClick={() => onSelectTab('ig-csv-analysis')}
            className={`flex items-center gap-space-md px-space-md py-space-sm rounded transition-all text-left ${
              activeTab === 'ig-csv-analysis'
                ? 'bg-surface-container-high text-primary font-medium shadow-[inset_2px_0_0_0_#4edea3]'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
            title="IG CSV Analysis"
          >
            <span className="material-symbols-outlined text-[18px] flex-shrink-0">table_chart</span>
            {!isCollapsed && <span className="font-body-md text-body-md truncate">IG CSV Analysis</span>}
          </button>

          {/* Trading 212 API */}
          <button
            onClick={() => onSelectTab('trading-212-api')}
            className={`flex items-center gap-space-md px-space-md py-space-sm rounded transition-all text-left ${
              activeTab === 'trading-212-api'
                ? 'bg-surface-container-high text-primary font-medium shadow-[inset_2px_0_0_0_#4edea3]'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
            title="Trading 212 API"
          >
            <span className="material-symbols-outlined text-[18px] flex-shrink-0">api</span>
            {!isCollapsed && <span className="font-body-md text-body-md truncate">Trading 212 API</span>}
          </button>

          {/* Reference Data */}
          <button
            onClick={() => onSelectTab('reference-data')}
            className={`flex items-center justify-between px-space-md py-space-sm rounded transition-all text-left group ${
              activeTab === 'reference-data'
                ? 'bg-surface-container-high text-primary font-medium shadow-[inset_2px_0_0_0_#4edea3]'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
            title={
              unresolvedCount > 0
                ? `Reference Data & Ticker Mapping — ${unresolvedCount} unmapped symbol(s)`
                : 'Reference Data & Ticker Mapping'
            }
          >
            <div className="flex items-center gap-space-md overflow-hidden">
              <span className="relative flex-shrink-0">
                <span className="material-symbols-outlined text-[18px] text-secondary">tune</span>
                {isCollapsed && unresolvedCount > 0 && (
                  <span className="absolute -top-0.5 -right-1 w-2 h-2 rounded-full bg-error" />
                )}
              </span>
              {!isCollapsed && <span className="font-body-md text-body-md truncate">Reference Data</span>}
            </div>
            {!isCollapsed && (
              <span
                className={`px-1.5 py-0.5 rounded font-label-caps text-[10px] ${
                  unresolvedCount > 0
                    ? 'bg-error-container text-on-error-container font-bold'
                    : 'bg-surface-container-highest text-secondary'
                }`}
              >
                {unresolvedCount > 0 ? `${unresolvedCount} UNMAPPED` : 'METADATA'}
              </span>
            )}
          </button>

          {/* Performance Blotter */}
          <button
            onClick={() => onSelectTab('performance-blotter')}
            className={`flex items-center gap-space-md px-space-md py-space-sm rounded transition-all text-left ${
              activeTab === 'performance-blotter'
                ? 'bg-surface-container-high text-primary font-medium shadow-[inset_2px_0_0_0_#4edea3]'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
            title="Performance Blotter"
          >
            <span className="material-symbols-outlined text-[18px] flex-shrink-0">candlestick_chart</span>
            {!isCollapsed && <span className="font-body-md text-body-md truncate">Performance Blotter</span>}
          </button>
        </nav>

        {/* System Feeds Status */}
        {!isCollapsed && (
          <>
            <div className="px-space-md pt-space-lg pb-space-xs">
              <span className="px-space-sm font-label-caps text-label-caps uppercase text-outline tracking-wider">
                System Feeds
              </span>
            </div>
            <div className="flex flex-col gap-space-xs px-space-md">
              <div
                className={`group relative flex items-center justify-between px-space-md py-space-xs rounded bg-surface-container-low border cursor-help ${
                  isBad ? 'border-error/50 bg-error-container/10' : 'border-surface-container/40'
                }`}
              >
                <span className="font-label-caps text-label-caps text-on-surface-variant">FEED STATUS</span>
                <span
                  className={`font-data-mono-sm text-data-mono-sm uppercase font-medium flex items-center gap-1.5 ${presentation.text}`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${presentation.dot} ${
                      presentation.pulse ? 'animate-pulse' : ''
                    }`}
                  ></span>
                  {presentation.label}
                </span>

                {/* Hover detail: names the error and which provider it came from. */}
                <div
                  role="tooltip"
                  className="pointer-events-none absolute left-full top-0 ml-2 w-72 z-50 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg border border-surface-container bg-surface-container-highest p-space-sm shadow-lg"
                >
                  <span className={`font-label-caps text-[10px] uppercase font-semibold block ${presentation.text}`}>
                    {FEED_HEADLINE[feed.state]}
                  </span>
                  {feed.detail.length > 0 && (
                    <ul className="mt-1.5 flex flex-col gap-1">
                      {feed.detail.map((line) => (
                        <li
                          key={line}
                          className="font-data-mono-sm text-[10px] leading-snug text-on-surface-variant break-words"
                        >
                          {line}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        {/* Collapsed rail: System Feeds is hidden, so keep a failure visible as a dot. */}
        {isCollapsed && isBad && (
          <div className="flex justify-center pt-space-lg" title={`${FEED_HEADLINE[feed.state]}\n${feed.detail.join('\n')}`}>
            <span className={`w-2.5 h-2.5 rounded-full ${presentation.dot} animate-pulse`}></span>
          </div>
        )}
      </div>

      {/* Scope Footer */}
      <div className="p-space-md bg-surface-container-low border-t border-surface-container/60 flex flex-col gap-space-sm">
        {!isCollapsed ? (
          <>
            <div className="flex items-center justify-between px-space-sm">
              <span className="font-label-caps text-label-caps text-outline uppercase">Scope</span>
              <span className="font-label-caps text-label-caps px-space-sm py-0.5 rounded bg-surface-container-highest text-secondary uppercase font-semibold">
                KAI FO
              </span>
            </div>
            <div className="flex items-center gap-space-sm px-space-sm pt-space-xs">
              <div className="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
              <span className="font-data-mono-sm text-data-mono-sm text-on-surface-variant">
                KAI Family Office v2.4
              </span>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center">
            <span className="font-label-caps text-label-caps px-1 py-0.5 rounded bg-surface-container-highest text-secondary uppercase">
              FO
            </span>
          </div>
        )}
      </div>
    </aside>
  );
};
