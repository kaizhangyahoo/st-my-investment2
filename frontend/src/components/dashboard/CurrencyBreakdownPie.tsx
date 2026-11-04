import React from 'react';
import { Card } from '../common/Card';
import { CurrencyAllocation } from '../../types';

interface CurrencyBreakdownProps {
  allocation?: CurrencyAllocation;
}

export const CurrencyBreakdownPie: React.FC<CurrencyBreakdownProps> = ({ allocation }) => {
  if (!allocation || allocation.total_gbp <= 0) {
    return (
      <Card title="Currency Exposure">
        <div className="h-48 flex items-center justify-center text-xs text-slate-400">No position data</div>
      </Card>
    );
  }

  const { usd_gbp, eur_gbp, gbp, total_gbp } = allocation;
  const usdPct = Math.round((usd_gbp / total_gbp) * 100);
  const eurPct = Math.round((eur_gbp / total_gbp) * 100);
  const gbpPct = Math.round((gbp / total_gbp) * 100);

  return (
    <Card title="Currency Exposure" subtitle="Asset equity normalized to GBP">
      <div className="space-y-3 pt-2">
        <div>
          <div className="flex justify-between text-xs font-medium mb-1">
            <span className="text-slate-600 dark:text-slate-300">USD (£{usd_gbp.toLocaleString(undefined, { maximumFractionDigits: 0 })})</span>
            <span className="text-slate-400">{usdPct}%</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2">
            <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${usdPct}%` }} />
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs font-medium mb-1">
            <span className="text-slate-600 dark:text-slate-300">GBP (£{gbp.toLocaleString(undefined, { maximumFractionDigits: 0 })})</span>
            <span className="text-slate-400">{gbpPct}%</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2">
            <div className="bg-emerald-500 h-2 rounded-full" style={{ width: `${gbpPct}%` }} />
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs font-medium mb-1">
            <span className="text-slate-600 dark:text-slate-300">EUR (£{eur_gbp.toLocaleString(undefined, { maximumFractionDigits: 0 })})</span>
            <span className="text-slate-400">{eurPct}%</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2">
            <div className="bg-amber-500 h-2 rounded-full" style={{ width: `${eurPct}%` }} />
          </div>
        </div>
      </div>
    </Card>
  );
};

