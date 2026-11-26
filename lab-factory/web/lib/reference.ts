// A reference case judged against its own expected answer: the analysis app's self-test.
// (Not an instrument-limit decision; those come only from the factory's check results.)
import type { AnalysisResult } from "./analysis.ts";
import { sig3 } from "./format.ts";
import type { ReferenceCase } from "./types.ts";

/**
 * Whether the app's answer for a case matches what the case expects: no decay when it expects none,
 * otherwise a found rate within `rel_tol` of the expected one, relatively.
 */
export function referencePassed(c: ReferenceCase, result: AnalysisResult): boolean {
  if (!c.expect.decay) return result.decay === false;
  const expected = c.expect.rate_constant_per_s;
  if (!result.decay || expected === undefined || expected === 0) return false;
  // A hair of slack so a found value exactly on the tolerance isn't failed by float rounding.
  return Math.abs(result.rate_constant_per_s - expected) / Math.abs(expected) <= c.rel_tol + 1e-12;
}

/** `no decay`, or `{k} per s` as the case states it. */
export function expectedLabel(c: ReferenceCase): string {
  const k = c.expect.rate_constant_per_s;
  return !c.expect.decay || k === undefined ? "no decay" : `${k} per s`;
}

/** The found rate to 3 significant figures and ` per s`, or `no decay`. */
export function foundLabel(result: AnalysisResult): string {
  return result.decay ? `${sig3(result.rate_constant_per_s)} per s` : "no decay";
}
