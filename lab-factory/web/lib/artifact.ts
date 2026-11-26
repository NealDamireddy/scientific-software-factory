// Reads the steps out of a submission's artifact, which the client types as `unknown`.
// Procedure artifacts are `{ steps: ProcedureStep[] }` and run plans are `RunPlan`.
// Defensive: anything malformed gives `null` rather than a half-read list, and `[]` means the
// artifact really lists no steps, so a caller never mistakes one for the other.
import type { Action, Amount, ProcedureStep, RunStep, Setting } from "./types.ts";

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function setting(value: unknown): Setting | null {
  if (!isObject(value) || typeof value.parameter !== "string" || !isNumber(value.value) || typeof value.unit !== "string") {
    return null;
  }
  return { parameter: value.parameter, value: value.value, unit: value.unit };
}

function settings(value: unknown): Setting[] | null {
  if (!Array.isArray(value)) return null;
  const read = value.map(setting);
  return read.every((s): s is Setting => s !== null) ? read : null;
}

function action(value: unknown): Action | null {
  if (!isObject(value) || typeof value.instrument_id !== "string" || typeof value.command !== "string") return null;
  const read = settings(value.settings);
  return read ? { instrument_id: value.instrument_id, command: value.command, settings: read } : null;
}

function amount(value: unknown): Amount | null {
  if (!isObject(value) || typeof value.what !== "string" || !isNumber(value.value) || typeof value.unit !== "string") {
    return null;
  }
  return { what: value.what, value: value.value, unit: value.unit };
}

function procedureStep(value: unknown): ProcedureStep | null {
  if (!isObject(value) || typeof value.text !== "string" || !isStringArray(value.citations)) return null;
  const step: ProcedureStep = { text: value.text, citations: [...value.citations] };
  if (value.action !== undefined) {
    const read = action(value.action);
    if (!read) return null;
    step.action = read;
  }
  if (value.amounts !== undefined) {
    if (!Array.isArray(value.amounts)) return null;
    const read = value.amounts.map(amount);
    if (!read.every((a): a is Amount => a !== null)) return null;
    step.amounts = read;
  }
  return step;
}

function runStep(value: unknown): RunStep | null {
  if (!isObject(value) || typeof value.command !== "string") return null;
  const read = settings(value.settings);
  return read ? { command: value.command, settings: read } : null;
}

function stepsOf<T>(artifact: unknown, read: (value: unknown) => T | null): T[] | null {
  if (!isObject(artifact) || !Array.isArray(artifact.steps)) return null;
  const steps = artifact.steps.map(read);
  return steps.every((s): s is T => s !== null) ? steps : null;
}

/** A procedure artifact's steps, or `null` when the artifact is malformed. */
export function procedureSteps(artifact: unknown): ProcedureStep[] | null {
  return stepsOf(artifact, procedureStep);
}

/** A run plan artifact's steps, or `null` when the artifact is malformed. */
export function runPlanSteps(artifact: unknown): RunStep[] | null {
  if (!isObject(artifact) || typeof artifact.instrument_id !== "string") return null;
  return stepsOf(artifact, runStep);
}

/** The artifact's steps for an order of the given kind, or `null` when the artifact is malformed. */
export function artifactSteps(kind: "procedure" | "run_plan", artifact: unknown): ProcedureStep[] | RunStep[] | null {
  return kind === "procedure" ? procedureSteps(artifact) : runPlanSteps(artifact);
}
