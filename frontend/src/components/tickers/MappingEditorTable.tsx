import React, { useState, useEffect } from 'react';
import { Card } from '../common/Card';
import { tickersApi } from '../../services/api';
import { Search, Save } from 'lucide-react';

export const MappingEditorTable: React.FC = () => {
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    tickersApi.getMappings().then((data) => {
      setEditing(data);
    });
  }, []);

  const handleTickerChange = (market: string, ticker: string) => {
    setEditing((prev) => ({ ...prev, [market]: ticker }));
  };

  const handleSave = async () => {
    await tickersApi.updateMappings(editing);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };


  const filtered = Object.keys(editing).filter((m) =>
    m.toLowerCase().includes(search.toLowerCase()) || editing[m].toLowerCase().includes(search.toLowerCase())
  );

  return (
    <Card
      title="Company Name to Ticker Resolution"
      subtitle="Map broker instrument names to Yahoo Finance tickers"
      action={
        <button
          onClick={handleSave}
          className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          <span>{saved ? 'Saved!' : 'Save Changes'}</span>
        </button>
      }
    >
      <div className="mb-4 relative">
        <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter instruments or tickers..."
          className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg pl-9 pr-4 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      <div className="max-h-72 overflow-y-auto border border-slate-200 dark:border-slate-800 rounded-lg">
        <table className="w-full text-left text-xs text-slate-600 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500 sticky top-0 border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th className="px-4 py-2 font-medium">Broker Market Name</th>
              <th className="px-4 py-2 font-medium">Yahoo Ticker</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {filtered.slice(0, 50).map((market) => (
              <tr key={market} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20">
                <td className="px-4 py-2 font-medium text-slate-800 dark:text-slate-200">{market}</td>
                <td className="px-4 py-2">
                  <input
                    type="text"
                    value={editing[market] || ''}
                    onChange={(e) => handleTickerChange(market, e.target.value)}
                    className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded px-2 py-1 font-mono text-xs focus:ring-1 focus:ring-blue-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-slate-400 mt-2">Showing up to 50 matching symbols. Edits persist to company_name_to_ticker.json.</p>
    </Card>
  );
};
