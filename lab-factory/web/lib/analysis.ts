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

/** `Rate constant {k} per s`, `Half-life {h} s`, `Fit error (RMS) {rms} AU`, or `No decay detected` and the RMS line. */
export function resultLines(result: AnalysisResult): string[] {
  const rms = `Fit error (RMS) ${sig3(result.rms_error)} AU`;
  if (!result.decay) return ["No decay detected", rms];
  return [`Rate constant ${sig3(result.rate_constant_per_s)} per s`, `Half-life ${sig3(result.half_life_s)} s`, rms];
}

/** The app's fitted curve, a_end + (a0 − a_end)·exp(−k·t), at the given times; none when no decay was found. */
export function fittedPoints(result: AnalysisResult, times: number[]): [number, number][] {
  if (!result.decay) return [];
  const { a0, a_end: aEnd, rate_constant_per_s: k } = result;
  return times.map((t) => [t, aEnd + (a0 - aEnd) * Math.exp(-k * t)]);
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
