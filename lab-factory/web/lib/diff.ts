import { canonicalJson } from "./digest.ts";
import type { ProcedureStep, RunStep } from "./types.ts";

type Step = ProcedureStep | RunStep;
type Field = "text" | "citations" | "action" | "amounts" | "command" | "settings";

export type StepChange = {
  change: "same" | "added" | "removed" | "changed";
  before?: number;
  after?: number;
  fields?: Field[];
};

const FIELDS: Field[] = ["text", "citations", "action", "amounts", "command", "settings"];

// Steps are aligned on their wording: `text` for a procedure step and
// `command` for a run step. The prefix keeps the two kinds from matching.
function keyOf(step: Step): string {
  return "text" in step ? `text:${step.text}` : `command:${step.command}`;
}

function fieldJson(step: Step, field: Field): string {
  const value = (step as Record<string, unknown>)[field];
  return value === undefined ? "" : canonicalJson(value);
}

// Indices are zero-based positions in `before` and `after`. The result follows
// the order of `after`; a removed step appears where it used to sit, ahead of
// any steps added in the same place.
export function diffSteps(before: Step[], after: Step[]): StepChange[] {
  const a = before.map(keyOf);
  const b = after.map(keyOf);

  // lcs[i][j] is the length of the longest common subsequence of a[i..] and b[j..].
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const changes: StepChange[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      const fields = FIELDS.filter((field) => fieldJson(before[i], field) !== fieldJson(after[j], field));
      if (fields.length === 0) changes.push({ change: "same", before: i, after: j });
      else changes.push({ change: "changed", before: i, after: j, fields });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      changes.push({ change: "removed", before: i });
      i += 1;
    } else {
      changes.push({ change: "added", after: j });
      j += 1;
    }
  }
  for (; i < a.length; i += 1) changes.push({ change: "removed", before: i });
  for (; j < b.length; j += 1) changes.push({ change: "added", after: j });
  return changes;
}
