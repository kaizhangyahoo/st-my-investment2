import React, { useEffect, useMemo, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';
import { PortfolioHistoryPoint } from '../../types';

interface EquityCurveChartProps {
  points: PortfolioHistoryPoint[];
  // Raw index closes in the index's own units; rebased here onto the first portfolio value.
  benchmark: { symbol: string; points: { date: string; value: number }[] } | null;
}

// Two or more consecutive business days with no stored value. A single one is a market holiday
// -- every interior miss in the stored accounts is an isolated date -- so breaking the line on
// one would litter a complete series with false gaps.
const GAP_BUSINESS_DAYS = 2;

const asUtc = (date: string) => new Date(`${date}T00:00:00Z`);

const isWeekend = (d: Date) => d.getUTCDay() === 0 || d.getUTCDay() === 6;

/** Business days strictly between two stored dates, i.e. how many are missing. */
const missingBusinessDays = (from: string, to: string): number => {
  const cursor = asUtc(from);
  const end = asUtc(to);
  let count = 0;
  cursor.setUTCDate(cursor.getUTCDate() + 1);
  while (cursor < end) {
    if (!isWeekend(cursor)) count += 1;
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return count;
};

/**
 * The series cut into runs of consecutive stored dates, plus the spans between them.
 *
 * A null inside one trace is not enough: it breaks the line but Plotly still joins every segment
 * into a single `tozeroy` fill, so the shaded area bridges the gap and the dropped dates read as a
 * flat day. One trace per run gives each run its own fill and leaves the gap genuinely empty.
 */
const splitOnGaps = (points: PortfolioHistoryPoint[]) => {
  const segments: PortfolioHistoryPoint[][] = [];
  const gaps: { from: string; to: string }[] = [];
  points.forEach((point, i) => {
    const gap =
      i > 0 && missingBusinessDays(points[i - 1].date, point.date) >= GAP_BUSINESS_DAYS;
    if (i === 0 || gap) {
      if (gap) gaps.push({ from: points[i - 1].date, to: point.date });
      segments.push([]);
    }
    segments[segments.length - 1].push(point);
  });
  return { segments, gaps };
};

/** Benchmark closes expressed as "what the portfolio's opening value would be worth". */
const rebase = (
  benchmarkPoints: { date: string; value: number }[],
  points: PortfolioHistoryPoint[],
) => {
  if (points.length === 0) return null;
  const from = points[0].date;
  const to = points[points.length - 1].date;
  const inWindow = benchmarkPoints.filter((p) => p.date >= from && p.date <= to);
  const base = inWindow.find((p) => p.value > 0);
  if (!base) return null;
  const scale = points[0].value / base.value;
  return {
    x: inWindow.map((p) => p.date),
    y: inWindow.map((p) => p.value * scale),
  };
};

export const EquityCurveChart: React.FC<EquityCurveChartProps> = ({ points, benchmark }) => {
  const plotRef = useRef<HTMLDivElement>(null);
  const series = useMemo(() => splitOnGaps(points), [points]);
  const benchmarkSeries = useMemo(
    () => (benchmark ? rebase(benchmark.points, points) : null),
    [benchmark, points],
  );

  useEffect(() => {
    const el = plotRef.current;
    if (!el || points.length === 0) return;

    const data: unknown[] = series.segments.map((segment) => ({
      x: segment.map((p) => p.date),
      y: segment.map((p) => p.value),
      type: 'scatter',
      mode: 'lines',
      name: 'Portfolio value',
      line: { color: '#4edea3', width: 2.5, shape: 'linear' },
      fill: 'tozeroy',
      fillcolor: 'rgba(78, 222, 163, 0.10)',
      hovertemplate: '%{x|%Y-%m-%d}<br>£%{y:,.2f}<extra></extra>',
    }));
    if (benchmarkSeries) {
      data.push({
        x: benchmarkSeries.x,
        y: benchmarkSeries.y,
        type: 'scatter',
        mode: 'lines',
        name: `${benchmark?.symbol} (rebased)`,
        line: { color: '#64B5F6', width: 1.5, dash: 'dot' },
        hovertemplate: `${benchmark?.symbol} rebased<br>%{x|%Y-%m-%d}<br>£%{y:,.2f}<extra></extra>`,
      });
    }

    const values = [
      ...points.map((p) => p.value),
      ...(benchmarkSeries ? benchmarkSeries.y : []),
    ];
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;

    Plotly.react(
      el,
      data,
      {
        autosize: true,
        height: 300,
        margin: { l: 62, r: 16, t: 10, b: 36 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#bbcabf', family: 'monospace', size: 10 },
        showlegend: false,
        hovermode: 'x unified',
        // The empty run between two segments already shows no line; the band labels it, so a
        // two-day gap is not mistaken for a hairline rendering artefact.
        shapes: series.gaps.map((gap) => ({
          type: 'rect',
          xref: 'x',
          yref: 'paper',
          x0: gap.from,
          x1: gap.to,
          y0: 0,
          y1: 1,
          fillcolor: 'rgba(255, 171, 64, 0.10)',
          line: { width: 0 },
          layer: 'below',
        })),
        xaxis: {
          gridcolor: '#1c2028',
          type: 'date',
          // Collapse weekends so horizontal distance tracks trading time, which is what makes
          // a real gap in the series visible as a gap.
          rangebreaks: [{ bounds: ['sat', 'mon'] }],
        },
        yaxis: {
          gridcolor: '#1c2028',
          // Fresh array per render: Plotly writes zoom results back into the range it is handed
          // (KAN-50), so a memoised one would drift.
          range: [lo - pad, hi + pad],
          tickprefix: '£',
          separatethousands: true,
        },
      },
      { displayModeBar: false, responsive: true },
    );
  }, [points, series, benchmark, benchmarkSeries]);

  useEffect(() => {
    const el = plotRef.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return (
    <div>
      <div ref={plotRef} className="w-full h-[300px]" />
      {series.gaps.length > 0 && (
        <span className="font-data-mono-sm text-[10px] text-outline block mt-1">
          {series.gaps.length} shaded break(s) mark dates with no stored value — not a flat day.
        </span>
      )}
    </div>
  );
};
