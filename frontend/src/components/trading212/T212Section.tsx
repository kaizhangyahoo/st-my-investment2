import React, { useState } from 'react';
import { Card } from '../common/Card';
import { t212Api } from '../../services/api';
import { T212AccountSummary, T212Position } from '../../types';

export const T212Section: React.FC = () => {
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [summary, setSummary] = useState<T212AccountSummary | null>(null);
  const [, setPositions] = useState<T212Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);


  const fetchT212Data = async () => {
    if (!apiKey || !apiSecret) {
      setError('Please provide both Trading 212 API Key and Secret');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [sum, pos] = await Promise.all([
        t212Api.getOverview(apiKey, apiSecret),
        t212Api.getPositions(apiKey, apiSecret),
      ]);
      setSummary(sum);
      setPositions(pos);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to authenticate with Trading 212');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card
        title="Trading 212 Portfolio Sync"
        subtitle="Live synchronization via Trading 212 REST API"
        action={
          <button
            onClick={fetchT212Data}
            disabled={loading}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
          >
            {loading ? 'Connecting...' : 'Fetch Live Positions'}
          </button>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-2">
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Trading 212 API Key</label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter API Key"
              className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-1.5 text-xs font-mono"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">Trading 212 API Secret</label>
            <input
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              placeholder="••••••••••••"
              className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-1.5 text-xs font-mono"
            />
          </div>
        </div>
        {error && <p className="text-xs text-rose-500 mt-2">{error}</p>}
      </Card>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-3 shadow-sm">
            <span className="text-[10px] text-slate-400 uppercase font-semibold">Total Portfolio</span>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">
              £{summary.total_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-3 shadow-sm">
            <span className="text-[10px] text-slate-400 uppercase font-semibold">Available Cash</span>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">
              £{summary.cash_available.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-3 shadow-sm">
            <span className="text-[10px] text-slate-400 uppercase font-semibold">Investments</span>
            <div className="text-lg font-bold text-slate-900 dark:text-slate-100">
              £{summary.investments_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-3 shadow-sm">
            <span className="text-[10px] text-slate-400 uppercase font-semibold">Unrealized P&L</span>
            <div className={`text-lg font-bold ${summary.unrealized_pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
              £{summary.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
