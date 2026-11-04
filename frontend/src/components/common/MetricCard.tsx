import React from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  isPositive?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({ label, value, delta, isPositive }) => {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 shadow-sm">
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">{label}</span>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="text-2xl font-bold text-slate-900 dark:text-slate-50">{value}</span>
        {delta && (
          <div className={`flex items-center text-xs font-semibold ${isPositive ? 'text-emerald-500' : 'text-rose-500'}`}>
            {isPositive ? <TrendingUp className="w-3.5 h-3.5 mr-1" /> : <TrendingDown className="w-3.5 h-3.5 mr-1" />}
            {delta}
          </div>
        )}
      </div>
    </div>
  );
};

