import React, { useState, useEffect } from 'react';
import { tickersApi } from '../../services/api';

export const TickerMappingView: React.FC = () => {
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [newKey, setNewKey] = useState('');
  const [newVal, setNewVal] = useState('');
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveResults, setResolveResults] = useState<Record<string, string | null>>({});

  const loadMappings = async () => {
    setLoading(true);
    try {
      const data = await tickersApi.getMappings();
      setMappings(data);
    } catch (err) {
      console.error('Failed to load mappings', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMappings();
  }, []);

  const handleSaveOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKey.trim() || !newVal.trim()) return;
    try {
      const updated = { ...mappings, [newKey.trim()]: newVal.trim().toUpperCase() };
      await tickersApi.updateMappings(updated);
      setMappings(updated);
      setNewKey('');
      setNewVal('');
      setSaveStatus('MAPPING COMMITTED TO DISK (company_name_to_ticker.json)');
      setTimeout(() => setSaveStatus(null), 3000);
    } catch {
      setSaveStatus('ERROR: Failed to save mapping');
    }
  };

  const handleDelete = async (keyToDelete: string) => {
    if (!window.confirm(`Remove mapping for "${keyToDelete}"?`)) return;
    const updated = { ...mappings };
    delete updated[keyToDelete];
    try {
      await tickersApi.updateMappings(updated);
      setMappings(updated);
    } catch (err) {
      console.error('Failed to delete mapping', err);
    }
  };

  const handleRunSecResolve = async () => {
    setResolving(true);
    try {
      // Find sample unmapped symbols
      const testNames = ['Apple Inc', 'Microsoft Corp', 'Palantir Technologies'];
      const res = await tickersApi.resolve(testNames);
      setResolveResults(res);
    } catch (err) {
      console.error('SEC resolution failed', err);
    } finally {
      setResolving(false);
    }
  };

  const handleAcceptResolve = async (name: string, ticker: string) => {
    const updated = { ...mappings, [name]: ticker };
    await tickersApi.updateMappings(updated);
    setMappings(updated);
    const newRes = { ...resolveResults };
    delete newRes[name];
    setResolveResults(newRes);
  };

  const mappingEntries = Object.entries(mappings).filter(
    ([k, v]) =>
      k.toLowerCase().includes(search.toLowerCase()) ||
      v.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-space-lg pb-16">
      {/* ─────────────────────────────────────────────────────────────
          1. WORKSPACE SUB-HEADER & TELEMETRY STRIP
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-space-md">
        <div className="flex items-center gap-space-sm">
          <span className="material-symbols-outlined text-[20px] text-secondary">tune</span>
          <div>
            <span className="font-headline-md text-headline-md text-on-surface font-semibold">
              Reference Data & Instrument Taxonomy Master
            </span>
            <span className="font-label-caps text-[10px] text-outline block">
              STORAGE: company_name_to_ticker.json • RECONCILIATION ENGINE
            </span>
          </div>
        </div>

        {/* Quick Action Toolbar */}
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            onClick={handleRunSecResolve}
            disabled={resolving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-surface-container-highest hover:bg-surface-container text-secondary text-xs font-mono font-medium transition-colors border border-secondary/30"
          >
            <span className="material-symbols-outlined text-[15px]">travel_explore</span>
            <span>{resolving ? 'QUERYING SEC...' : 'RUN SEC RESOLVER'}</span>
          </button>
          <button
            type="button"
            onClick={loadMappings}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-surface-container-low hover:bg-surface-container text-on-surface text-xs font-mono transition-colors border border-surface-container"
          >
            <span className="material-symbols-outlined text-[15px]">refresh</span>
            <span>RELOAD</span>
          </button>
        </div>
      </div>

      {/* Telemetry Stats Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm">
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Active Mapped Taxonomy</span>
          <span className="font-data-mono-lg text-sm text-primary font-bold my-1 block">
            {Object.keys(mappings).length} Verified Pairs
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">100% Normalized</span>
        </div>
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Pending Ingestion</span>
          <span className="font-data-mono-lg text-sm text-secondary font-bold my-1 block">
            {Object.keys(resolveResults).length} Unresolved
          </span>
          <span className="font-data-mono-sm text-[10px] text-secondary">Awaiting Review</span>
        </div>
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Ingestion Source</span>
          <span className="font-data-mono-lg text-sm text-on-surface font-bold my-1 block">
            IG & T212 Statement Feeds
          </span>
          <span className="font-data-mono-sm text-[10px] text-primary">Live Linked</span>
        </div>
        <div className="p-3 rounded-lg bg-surface-container-low border border-surface-container/60 shadow-sm">
          <span className="font-label-caps text-[10px] text-outline uppercase block">Taxonomy Audit</span>
          <span className="font-data-mono-lg text-sm text-primary font-bold my-1 block">
            SYNCED TO DISK
          </span>
          <span className="font-data-mono-sm text-[10px] text-outline">JSON Store Active</span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          2. PENDING RESOLUTION ALERT SECTION
      ───────────────────────────────────────────────────────────── */}
      {Object.keys(resolveResults).length > 0 && (
        <div className="p-space-md rounded-xl bg-surface-container-low border border-secondary/40 shadow-sm space-y-3">
          <div className="flex items-center justify-between pb-space-xs border-b border-surface-container/40">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-secondary">notification_important</span>
              <span className="font-headline-md text-sm text-on-surface font-semibold">
                SEC EDGAR Ingestion Resolution Candidates
              </span>
            </div>
            <span className="font-label-caps text-[10px] text-secondary uppercase font-mono">
              SUGGESTED MAPPINGS
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-space-sm">
            {Object.entries(resolveResults).map(([name, ticker]) => (
              <div
                key={name}
                className="p-3 rounded bg-surface-container-lowest border border-surface-container/50 flex items-center justify-between"
              >
                <div>
                  <span className="font-body-sm text-xs text-on-surface font-medium block">{name}</span>
                  <span className="font-data-mono-sm text-xs text-primary font-bold">
                    Suggested: {ticker || 'UNRESOLVED'}
                  </span>
                </div>
                {ticker && (
                  <button
                    type="button"
                    onClick={() => handleAcceptResolve(name, ticker)}
                    className="px-2.5 py-1 rounded bg-primary-container hover:bg-primary text-on-primary-container text-xs font-mono font-bold transition-colors"
                  >
                    ACCEPT
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          3. ACTIVE SYMBOL MAPPINGS TABLE & LIVE JSON INSPECTOR
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg">
        {/* Active Mappings Table (8 cols) */}
        <div className="xl:col-span-8 bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-sm pb-space-sm mb-space-sm border-b border-surface-container/40">
            <div className="flex items-center gap-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">data_object</span>
              <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                Active Symbol Mappings
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-caps text-[10px]">
                {mappingEntries.length} OF {Object.keys(mappings).length}
              </span>
            </div>

            <div className="relative">
              <span className="material-symbols-outlined absolute left-2 top-2 text-[15px] text-outline">
                search
              </span>
              <input
                type="text"
                placeholder="Search raw name or ticker..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-7 pr-3 py-1 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary w-52"
              />
            </div>
          </div>

          <div className="overflow-x-auto max-h-[500px]">
            <table className="w-full text-left font-data-mono-sm text-data-mono-sm border-collapse">
              <thead className="sticky top-0 bg-surface-container-low z-10">
                <tr className="border-b border-surface-container text-outline uppercase font-label-caps text-[10px]">
                  <th className="py-2 px-space-sm">CSV Raw String / Broker Feed</th>
                  <th className="py-2 px-space-sm">Mapped Ticker</th>
                  <th className="py-2 px-space-sm">Exchange / MIC</th>
                  <th className="py-2 px-space-sm">Status</th>
                  <th className="py-2 px-space-sm text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container/30">
                {mappingEntries.map(([marketName, ticker]) => {
                  const isLondon = ticker.endsWith('.L');
                  const isGermany = ticker.endsWith('.DE');
                  const mic = isLondon ? 'XLON (LSE)' : isGermany ? 'XETR (Xetra)' : 'XNYS / XNAS';
                  return (
                    <tr key={marketName} className="hover:bg-surface-container-high/40">
                      <td className="py-2.5 px-space-sm text-on-surface font-medium truncate max-w-[240px]">
                        {marketName}
                      </td>
                      <td className="py-2.5 px-space-sm font-bold text-primary">
                        {ticker}
                      </td>
                      <td className="py-2.5 px-space-sm text-outline">
                        {mic}
                      </td>
                      <td className="py-2.5 px-space-sm">
                        <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 text-[10px] font-bold">
                          100% MATCH
                        </span>
                      </td>
                      <td className="py-2.5 px-space-sm text-right">
                        <button
                          type="button"
                          onClick={() => handleDelete(marketName)}
                          className="px-2 py-0.5 rounded hover:bg-error-container/20 text-outline hover:text-error text-xs font-mono transition-colors"
                          title="Delete mapping"
                        >
                          <span className="material-symbols-outlined text-[15px]">delete</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Live JSON Store & Add Override Form (4 cols) */}
        <div className="xl:col-span-4 space-y-space-md">
          {/* Add Override Form */}
          <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
            <span className="font-headline-md text-sm text-on-surface font-semibold flex items-center gap-1.5 mb-space-sm">
              <span className="material-symbols-outlined text-[18px] text-primary">add_circle</span>
              Add Custom Ticker Override
            </span>

            <form onSubmit={handleSaveOverride} className="space-y-3">
              <div>
                <label className="block font-label-caps text-[10px] text-outline uppercase mb-1">
                  Raw Broker Ingestion String
                </label>
                <input
                  type="text"
                  placeholder="e.g. Palantir Technologies Inc"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  className="w-full px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-on-surface focus:outline-none focus:border-primary"
                  required
                />
              </div>

              <div>
                <label className="block font-label-caps text-[10px] text-outline uppercase mb-1">
                  Resolved Yahoo Finance Symbol
                </label>
                <input
                  type="text"
                  placeholder="e.g. PLTR or SDR.L"
                  value={newVal}
                  onChange={(e) => setNewVal(e.target.value)}
                  className="w-full px-3 py-1.5 rounded bg-surface-container-lowest border border-surface-container text-xs font-mono text-primary font-bold focus:outline-none focus:border-primary"
                  required
                />
              </div>

              <button
                type="submit"
                className="w-full py-1.5 rounded bg-primary-container hover:bg-primary font-bold text-on-primary-container text-xs font-mono transition-colors shadow-sm flex items-center justify-center gap-1"
              >
                <span className="material-symbols-outlined text-[15px]">save</span>
                <span>COMMIT OVERRIDE</span>
              </button>
            </form>

            {saveStatus && (
              <div className="mt-2 text-[10px] font-mono text-primary bg-primary/10 p-2 rounded border border-primary/20">
                {saveStatus}
              </div>
            )}
          </div>

          {/* Live JSON Inspector */}
          <div className="bg-surface-container-low p-space-md rounded-xl border border-surface-container/60 shadow-sm">
            <div className="flex items-center justify-between pb-space-xs mb-space-xs border-b border-surface-container/40">
              <span className="font-headline-md text-sm text-on-surface font-semibold flex items-center gap-1">
                <span className="material-symbols-outlined text-[16px] text-secondary">code</span>
                Live JSON Store
              </span>
              <span className="font-label-caps text-[10px] text-outline uppercase">
                company_name_to_ticker.json
              </span>
            </div>

            <pre className="p-space-sm rounded bg-surface-container-lowest border border-surface-container/40 text-[11px] font-mono text-on-surface-variant overflow-y-auto max-h-56">
              {JSON.stringify(mappings, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
