// Reading what the analysis app and the simulation return, and the lines and curve the
// Results tab shows from it. The app decides the answer; this only presents it.
import { sig3 } from "./format.ts";

export type AnalysisResult =
  | { decay: true; rate_constant_per_s: number; half_life_s: number; a0: number; a_end: number; rms_error: number }
  | { decay: false; rms_error: number };

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** The analysis app's answer, or null when it isn't one. */
export function readAnalysisResult(value: unknown): AnalysisResult | null {
  if (!isObject(value) || typeof value.decay !== "boolean" || !isNumber(value.rms_error)) return null;
  if (!value.decay) return { decay: false, rms_error: value.rms_error };
  const { rate_constant_per_s: k, half_life_s: h, a0, a_end: aEnd } = value;
  if (!isNumber(k) || !isNumber(h) || !isNumber(a0) || !isNumber(aEnd)) return null;
  return { decay: true, rate_constant_per_s: k, half_life_s: h, a0, a_end: aEnd, rms_error: value.rms_error };
}

/**
 * `Rate constant {k} per s`, `Half-life {h} s`, `Fit error (RMS) {rms} AU`, or `No decay detected` and the RMS line.
 * A fit error under 1e-9 is floating-point noise around an exact fit, so it reads as `0 AU`.
 */
export function resultLines(result: AnalysisResult): string[] {
  const error = Math.abs(result.rms_error) < 1e-9 ? 0 : result.rms_error;
  const rms = `Fit error (RMS) ${sig3(error)} AU`;
  if (!result.decay) return ["No decay detected", rms];
  return [`Rate constant ${sig3(result.rate_constant_per_s)} per s`, `Half-life ${sig3(result.half_life_s)} s`, rms];
}

/** The app's fitted curve, a_end + (a0 − a_end)·exp(−k·t), at the given times; none when no decay was found. */
export function fittedPoints(result: AnalysisResult, times: number[]): [number, number][] {
  if (!result.decay) return [];
  const { a0, a_end: aEnd, rate_constant_per_s: k } = result;
  return times.map((t) => [t, aEnd + (a0 - aEnd) * Math.exp(-k * t)]);
}

/** How many points the drawn fit line has. */
export const FIT_LINE_POINTS = 200;

/**
 * The app's fitted curve as a line to draw: 200 evenly spaced times from the earliest reading to the
 * latest, in order, from the returned a0, a_end and rate alone. None when no decay was found.
 */
export function fitLine(result: AnalysisResult, times: number[]): [number, number][] {
  if (!result.decay || times.length === 0) return [];
  let low = Infinity;
  let high = -Infinity;
  for (const t of times) {
    if (t < low) low = t;
    if (t > high) high = t;
  }
  const grid = Array.from({ length: FIT_LINE_POINTS }, (_, i) =>
    i === FIT_LINE_POINTS - 1 ? high : low + ((high - low) * i) / (FIT_LINE_POINTS - 1));
  return fittedPoints(result, grid);
}

/** The data table's rows: one per reading, in file order: time, absorbance and (when there's a fit) the fitted value. */
export function readingRows(readings: { time_s: number[]; absorbance: number[] }, result: AnalysisResult): { x: number; values: (number | null)[] }[] {
  const fit = fittedPoints(result, readings.time_s);
  return readings.time_s.map((t, i) => ({ x: t, values: result.decay ? [readings.absorbance[i], fit[i][1]] : [readings.absorbance[i]] }));
}

/** The status line when an analysis finishes: `Analyzed {file}. Rate constant {k} per s.` or `Analyzed {file}. No decay detected.` */
export function completionLine(file: string, result: AnalysisResult): string {
  if (!result.decay) return `Analyzed ${file}. No decay detected.`;
  return `Analyzed ${file}. Rate constant ${sig3(result.rate_constant_per_s)} per s.`;
}

const ALL_TIMES_EQUAL = "time_s must increase.";

/** The analysis app's error as the Results tab shows it: the all-times-equal error reworded, others as they are. */
export function analysisMessage(message: string): string {
  if (message === ALL_TIMES_EQUAL) return "The time_s values are all the same. The analysis needs readings at different times.";
  return message;
}

export type SimulatedSeries = { label: string; points: [number, number][] };

/** The simulation's `{ series: [{ label, points }] }`, or null when it isn't that. */
export function readSimulation(value: unknown): SimulatedSeries[] | null {
  if (!isObject(value) || !Array.isArray(value.series)) return null;
  const series: SimulatedSeries[] = [];
  for (const s of value.series) {
    if (!isObject(s) || typeof s.label !== "string" || !Array.isArray(s.points)) return null;
    const points: [number, number][] = [];
    for (const p of s.points) {
      if (!Array.isArray(p) || p.length !== 2 || !isNumber(p[0]) || !isNumber(p[1])) return null;
      points.push([p[0], p[1]]);
    }
    series.push({ label: s.label, points });
  }
  return series;
}
