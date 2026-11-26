// The geometry and words behind a plot: scales, axes with nice ticks, tick labels, a summary for
// screen readers and the rows of its data table. Pure, so it runs under node --test.
import { niceTicks } from "./ticks.ts";

export type PlotSeries = { label: string; points: [number, number][]; style: "points" | "line" };
export type Axis = { domain: [number, number]; ticks: number[] };

/** Maps `domain` linearly onto `range`; a zero-width domain maps to the middle of the range. */
export function linearScale(domain: [number, number], range: [number, number]): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  if (d1 === d0) return () => (r0 + r1) / 2;
  return (value) => r0 + ((value - d0) / (d1 - d0)) * (r1 - r0);
}

/** Draws an axis over [low, high], or over 0 to 1 when there's nothing to cover (low > high). */
function axis(min: number, max: number, count: number): Axis {
  let low = min <= max ? min : 0;
  let high = min <= max ? max : 1;
  if (low === high) {
    const pad = low === 0 ? 1 : Math.abs(low) * 0.1;
    low -= pad;
    high += pad;
  }
  const ticks = niceTicks(low, high, count);
  return { domain: [ticks[0], ticks[ticks.length - 1]], ticks };
}

/** Axes that cover every series' points, ending on ticks. */
export function plotAxes(series: PlotSeries[], counts: { x: number; y: number } = { x: 6, y: 5 }): { x: Axis; y: Axis } {
  // Loops, not Math.min(...values): spreading a long series overflows the call stack.
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const s of series) {
    for (const [px, py] of s.points) {
      if (px < x0) x0 = px;
      if (px > x1) x1 = px;
      if (py < y0) y0 = py;
      if (py > y1) y1 = py;
    }
  }
  return { x: axis(x0, x1, counts.x), y: axis(y0, y1, counts.y) };
}

function decimalsOf(step: number): number {
  for (let d = 0; d < 12; d += 1) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6) return d;
  }
  return 12;
}

/** A tick written with as many decimals as the tick step needs, so the labels line up: 0.05, 0.10. */
export function tickLabel(value: number, ticks: number[]): string {
  const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : Math.abs(value) || 1;
  const text = (value === 0 ? 0 : value).toFixed(decimalsOf(step));
  return /^-0(\.0+)?$/.test(text) ? text.slice(1) : text;
}

/** `Readings and fit. Readings: 61 points. Fit: line.` */
export function seriesSummary(title: string, series: PlotSeries[]): string {
  if (series.length === 0) return `${title}. No data.`;
  const parts = series.map((s) => {
    if (s.style === "line") return `${s.label}: line.`;
    return `${s.label}: ${s.points.length} ${s.points.length === 1 ? "point" : "points"}.`;
  });
  return `${title}. ${parts.join(" ")}`;
}

export type DataRow = { x: number; values: (number | null)[] };

function sharesGrid(series: PlotSeries[]): boolean {
  const first = series[0].points;
  return series.every((s) => s.points.length === first.length && s.points.every((p, i) => p[0] === first[i][0]));
}

/**
 * The rows of a plot's data table. Series on one shared x grid (the simulation's curves) are joined
 * by index, one row per grid point. Otherwise every point gets its own row, in order, series by
 * series, so readings that share a time are all kept.
 */
export function dataRows(series: PlotSeries[]): DataRow[] {
  if (series.length === 0) return [];
  if (sharesGrid(series)) {
    return series[0].points.map((p, i) => ({ x: p[0], values: series.map((s) => s.points[i][1]) }));
  }
  const rows: DataRow[] = [];
  series.forEach((s, j) => {
    for (const [x, y] of s.points) rows.push({ x, values: series.map((_, k) => (k === j ? y : null)) });
  });
  return rows;
}

/** The most points a points series draws; more are sampled down to this. */
export const DRAW_LIMIT = 2000;
/** The most rows a data table shows. */
export const TABLE_LIMIT = 2000;

/** The points to draw: all of them up to `limit`, else `limit` evenly spaced ones, first and last included. */
export function drawnPoints<T>(points: T[], limit: number = DRAW_LIMIT): T[] {
  if (points.length <= limit) return points;
  const drawn: T[] = [];
  const last = points.length - 1;
  for (let i = 0; i < limit; i += 1) drawn.push(points[Math.round((i * last) / (limit - 1))]);
  return drawn;
}

function count(n: number): string {
  return n.toLocaleString("en-GB");
}

/** `Showing 2,000 of {n} readings. The analysis used all of them.` */
export function samplingNote(total: number): string {
  return `Showing ${count(DRAW_LIMIT)} of ${count(total)} readings. The analysis used all of them.`;
}

/** `Showing the first 2,000 of {n} rows.` */
export function tableNote(total: number): string {
  return `Showing the first ${count(TABLE_LIMIT)} of ${count(total)} rows.`;
}
