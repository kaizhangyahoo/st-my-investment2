import React from 'react';
import { Card } from '../common/Card';
import { Position } from '../../types';

interface PositionsTableProps {
  positions: Position[];
}

export const PositionsTable: React.FC<PositionsTableProps> = ({ positions }) => {
  return (
    <Card title="Current Holdings" subtitle={`${positions.length} active positions`}>
      <div className="overflow-x-auto -mx-5 -mb-5">
        <table className="w-full text-left text-xs text-slate-600 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-slate-800/50 text-slate-500 uppercase font-medium border-y border-slate-200 dark:border-slate-800">
            <tr>
              <th className="px-5 py-3">Market</th>
              <th className="px-4 py-3">Ticker</th>
              <th className="px-4 py-3 text-right">Quantity</th>
              <th className="px-4 py-3 text-right">Price</th>
              <th className="px-4 py-3 text-right">Market Value (GBP)</th>
              <th className="px-5 py-3 text-right">P&L (GBP)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {positions.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-slate-400">
                  No active positions loaded. Upload trade history CSV above.
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const isPos = pos.pnl_gbp >= 0;
                return (
                  <tr key={pos.ticker} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
                    <td className="px-5 py-3 font-medium text-slate-900 dark:text-slate-100">{pos.market}</td>
                    <td className="px-4 py-3 font-mono text-slate-500">{pos.ticker}</td>
                    <td className="px-4 py-3 text-right">{pos.quantity.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right">
                      {pos.current_price ? `${pos.current_price.toFixed(2)} ${pos.currency}` : '—'}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-slate-900 dark:text-slate-100">
                      £{pos.market_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className={`px-5 py-3 text-right font-semibold ${isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                      {isPos ? '+' : ''}£{pos.pnl_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
};

