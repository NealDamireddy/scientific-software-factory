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

function axis(values: number[], count: number): Axis {
  let low = values.length > 0 ? Math.min(...values) : 0;
  let high = values.length > 0 ? Math.max(...values) : 1;
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
  const points = series.flatMap((s) => s.points);
  return { x: axis(points.map((p) => p[0]), counts.x), y: axis(points.map((p) => p[1]), counts.y) };
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
  const text = value.toFixed(decimalsOf(step));
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

/** One row per x value, in order, with each series' y at that x (null where it has none). */
export function dataRows(series: PlotSeries[]): DataRow[] {
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
  const lookups = series.map((s) => new Map(s.points.map((p) => [p[0], p[1]])));
  return xs.map((x) => ({ x, values: lookups.map((m) => m.get(x) ?? null) }));
}
