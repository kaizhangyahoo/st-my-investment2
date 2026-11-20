import React, { useEffect, useRef, useState } from 'react';
import Plotly from 'plotly.js-dist-min';
import { marketDataApi, OhlcResponse } from '../../services/api';

type PlotlyHTMLElement = HTMLDivElement & {
  on?: (event: string, handler: (e: Record<string, unknown>) => void) => void;
  removeAllListeners?: (event: string) => void;
};

export interface ChartTrade {
  date: string; // YYYY-MM-DD
  side: 'BUY' | 'SELL';
  qty: number;
  price: number | null;
}

interface PriceTradeChartProps {
  ticker: string;
  trades: ChartTrade[];
}

const isoDaysAgo = (from: Date, days: number) => {
  const d = new Date(from);
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
};

// Mirrors the Streamlit "Trade history for <symbol>" chart: close-price line with BUY/SELL markers.
export const PriceTradeChart: React.FC<PriceTradeChartProps> = ({ ticker, trades }) => {
  const plotRef = useRef<PlotlyHTMLElement>(null);
  const initialYRange = useRef<[number, number] | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [ohlc, setOhlc] = useState<OhlcResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const earliestTrade = trades.reduce<string | null>((min, t) => (!min || t.date < min ? t.date : min), null);
  const startDate = earliestTrade
    ? isoDaysAgo(new Date(earliestTrade), 30)
    : isoDaysAgo(new Date(), 365);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setOhlc(null);
    marketDataApi
      .getOhlc(ticker, startDate)
      .then((res) => {
        if (!cancelled) setOhlc(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to load price history');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, startDate]);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || !ohlc || ohlc.points.length === 0) return;

    const closeByDate = new Map(ohlc.points.map((p) => [p.date, p.close]));
    const sortedDates = ohlc.points.map((p) => p.date);
    // Trades on weekends/holidays have no bar of their own; use the last close on or before them.
    const closeNear = (date: string): number | null => {
      const exact = closeByDate.get(date);
      if (exact !== undefined) return exact;
      let lo = 0;
      let hi = sortedDates.length - 1;
      let idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (sortedDates[mid] <= date) {
          idx = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      const fallback = idx >= 0 ? sortedDates[idx] : sortedDates[0];
      return closeByDate.get(fallback) ?? null;
    };
    // IG reports fills in minor units (cents/pence, e.g. 4988.0 for $49.88) and sometimes as 0.0.
    // Rescale each fill to the chart's quote unit; if no scale lands near the market, use the close.
    const markerY = (t: ChartTrade): number | null => {
      const ref = closeNear(t.date);
      if (t.price === null || ref === null || ref <= 0) return t.price ?? ref;
      let best = t.price;
      let bestDist = Infinity;
      for (const scale of [1, 0.01, 100]) {
        const dist = Math.abs(Math.log((t.price * scale) / ref));
        if (dist < bestDist) {
          bestDist = dist;
          best = t.price * scale;
        }
      }
      return bestDist <= Math.log(2) ? best : ref;
    };
    const sideTrace = (side: 'BUY' | 'SELL') => {
      const rows = trades
        .filter((t) => t.side === side && /^\d{4}-\d{2}-\d{2}$/.test(t.date))
        .map((t) => ({ t, y: markerY(t) }))
        .filter((r): r is { t: ChartTrade; y: number } => r.y !== null);
      const isBuy = side === 'BUY';
      return {
        x: rows.map((r) => r.t.date),
        y: rows.map((r) => r.y),
        mode: 'markers+text',
        type: 'scatter',
        name: side,
        marker: {
          symbol: isBuy ? 'triangle-up' : 'triangle-down',
          size: 13,
          color: isBuy ? '#4edea3' : '#ffb4ab',
          line: { width: 1, color: '#ffffff' },
        },
        text: rows.map((r) => `${side} ${r.t.qty}`),
        textposition: isBuy ? 'top center' : 'bottom center',
        textfont: { size: 10, color: isBuy ? '#4edea3' : '#ffb4ab', family: 'monospace' },
        hovertemplate: `<b>${side}</b> %{text}<br>%{x|%Y-%m-%d}<br>Price: %{y:,.2f}<extra></extra>`,
      };
    };

    const buyTrace = sideTrace('BUY');
    const sellTrace = sideTrace('SELL');
    const data = [
      {
        x: ohlc.points.map((p) => p.date),
        y: ohlc.points.map((p) => p.close),
        type: 'scatter',
        mode: 'lines',
        name: 'Close',
        line: { color: '#64B5F6', width: 2 },
        fill: 'tozeroy',
        fillcolor: 'rgba(100, 181, 246, 0.08)',
        hovertemplate: '%{x|%Y-%m-%d}<br>Close: %{y:,.2f}<extra></extra>',
      },
      buyTrace,
      sellTrace,
    ];

    const ys = [...ohlc.points.map((p) => p.close), ...buyTrace.y, ...sellTrace.y];
    const lo = Math.min(...ys);
    const hi = Math.max(...ys);
    const pad = (hi - lo) * 0.1 || hi * 0.05;
    initialYRange.current = [lo - pad, hi + pad];

    const layout = {
      autosize: true,
      height: 300,
      margin: { l: 50, r: 16, t: 10, b: 36 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#bbcabf', family: 'monospace', size: 10 },
      showlegend: false,
      hovermode: 'closest',
      xaxis: { gridcolor: '#1c2028', type: 'date' },
      yaxis: {
        gridcolor: '#1c2028',
        // Copy: Plotly writes zoom results back into the range array it is given, so handing it
        // initialYRange.current directly would let a zoom overwrite our record of the full view.
        range: [...initialYRange.current],
        title: { text: ohlc.currency ? `Price (${ohlc.currency})` : 'Price' },
      },
    };

    Plotly.react(el, data, layout, { displayModeBar: false, responsive: true });
    setZoomed(false);
    const onRelayout = (e: Record<string, unknown>) => {
      if (Object.keys(e).some((k) => k.startsWith('xaxis.range') || k.startsWith('yaxis.range'))) {
        setZoomed(true);
      }
    };
    el.on?.('plotly_relayout', onRelayout);
    return () => {
      el.removeAllListeners?.('plotly_relayout');
    };
  }, [ohlc, trades]);

  const resetView = () => {
    const el = plotRef.current;
    if (!el || !initialYRange.current) return;
    Plotly.relayout(el, {
      'xaxis.autorange': true,
      'yaxis.range': [...initialYRange.current],
    }).then(() => setZoomed(false));
  };

  useEffect(() => {
    const el = plotRef.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  const empty = !loading && !error && (!ohlc || ohlc.points.length === 0);

  return (
    <div className="relative w-full h-[300px]">
      <div ref={plotRef} className="w-full h-full" />
      {ohlc && ohlc.points.length > 0 && (
        <button
          type="button"
          onClick={resetView}
          title="Reset zoom to the full price history"
          className={`absolute top-1 right-2 z-10 flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-mono transition-colors ${
            zoomed
              ? 'bg-primary/15 border-primary/40 text-primary hover:bg-primary/25'
              : 'bg-surface-container border-surface-container-high text-outline hover:text-on-surface'
          }`}
        >
          <span className="material-symbols-outlined text-[13px]">zoom_out_map</span>
          RESET VIEW
        </button>
      )}
      {(loading || error || empty) && (
        <div className="absolute inset-0 flex items-center justify-center text-xs font-mono text-outline">
          {loading
            ? `Loading ${ticker} price history...`
            : error
            ? `Price history unavailable: ${error}`
            : `No price history returned for ${ticker}`}
        </div>
      )}
    </div>
  );
};
