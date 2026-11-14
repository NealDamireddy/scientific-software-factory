// Producer captures are generated offline by tests.test_workspace_golden.
// Only the fixture adapter creates tab-local records.
import capture from "../../fixtures/workspace/producer-records.json";
import type { Calibration, Lab, Pin, Project, Revision, SpecInput, Specification } from "./api";

export function pin({ lab_id, project_id, revision, sha256 }: Pin): Pin {
  return { lab_id, project_id, revision, sha256 };
}

function compareCodePoints(left: string, right: string): number {
  // Python orders Unicode scalars. JS string comparison orders UTF-16 units.
  for (let i = 0; i < left.length && i < right.length;) {
    const a = left.codePointAt(i)!;
    const b = right.codePointAt(i)!;
    if (a !== b) return a - b;
    i += a > 0xffff ? 2 : 1;
  }
  return left.length - right.length;
}

// Match canonical_json(json.loads(exported JSON)). The browser's wire format
// determines which tokens Python reads as integers, including 0 for JS -0.
function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) throw new TypeError("Fixture records require finite JSON numbers.");
  if (value !== 0 && Math.abs(value) < 1e-4) {
    const [significand, exponent] = value.toExponential().split("e-");
    return significand + "e-" + exponent.padStart(2, "0");
  }
  return JSON.stringify(value);
}

export function canonical(value: unknown): string {
  if (typeof value === "number") return canonicalNumber(value);
  if (typeof value === "string" && /[\uD800-\uDFFF]/u.test(value))
    throw new TypeError("Fixture record strings must be encodable as UTF-8.");
  if (Array.isArray(value)) return "[" + Array.from(value, item => canonical(item ?? null)).join(",") + "]";
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    // Optional fields with undefined values are absent from the exported JSON.
    const keys = Object.keys(record).filter(key => record[key] !== undefined);
    return "{" + keys.sort(compareCodePoints).map(key =>
      canonical(key) + ":" + canonical(record[key])
    ).join(",") + "}";
  }
  return JSON.stringify(value);
}
export async function digest(value: unknown): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}

type ContextHeader = Pin & {
  revision_id: string;
  kind: string;
  lab_revision: number | null;
  lab_sha256: string | null;
};
export type ContextRecord<T> = Revision<T> & ContextHeader;
type CompleteSpec = SpecInput & Pick<Project, "protocol_id" | "protocol_revision" | "analysis_method" | "scientific_objective">
  & Pick<Lab, "approved_libraries" | "operating_restrictions"> & {
    project: ContextHeader; lab: ContextHeader; specification_id: string; revision: number; verification_contract: string;
  };
export type SpecRecord = { origin: "producer" | "fixture-session"; payload: CompleteSpec };

export function specificationView(payload: CompleteSpec) {
  const { specification_id, revision, instrument, experiment_type, sample_ids, standards, calibration,
    settings, schedule, units, outputs, validation_criteria } = payload;
  return { specification_id, revision, instrument, experiment_type, sample_ids, standards, calibration,
    settings, schedule, units, outputs, validation_criteria, lab: pin(payload.lab), project: pin(payload.project) };
}

function contextHeader<T>(record: Revision<T>): ContextHeader {
  const { revision_id, kind, lab_revision, lab_sha256 } = record as ContextRecord<T>;
  return { ...pin(record), revision_id, kind, lab_revision, lab_sha256 };
}

// Select only public scientific fields. A caller may pass a saved projection
// that also contains approval, unresolved fields, status and the old digest.
export function sessionSpec(input: SpecInput, specification_id: string, revision: number,
  lab: Revision<Lab>, project: Revision<Project>): CompleteSpec {
  const { instrument, experiment_type, sample_ids, standards, calibration, settings, schedule, units, outputs, validation_criteria } = input;
  const { protocol_id, protocol_revision, analysis_method, scientific_objective } = project.payload;
  return { specification_id, revision, instrument, experiment_type, sample_ids, standards, calibration, settings, schedule,
    units, outputs, validation_criteria, protocol_id, protocol_revision, analysis_method, scientific_objective,
    approved_libraries: lab.payload.approved_libraries, operating_restrictions: lab.payload.operating_restrictions,
    lab: contextHeader(lab), project: contextHeader(project), verification_contract: experiment_type + "@1" };
}

export const golden = {
  lab: capture.lab,
  project: capture.project,
  calibration: capture.calibration,
  specifications: capture.specifications.map(({payload, sha256, approval, unresolved_fields}) => ({
    sha256, approval, unresolved_fields, payload: payload as CompleteSpec,
  })),
};

export function matchesFrozenCalibration(reference: Calibration, spec: SpecInput): boolean {
  const fit = golden.calibration.payload;
  return fit.lab_id === spec.lab.lab_id && fit.project_id === spec.project.project_id &&
    fit.profile_id === spec.instrument.profile_id && canonical(golden.calibration.reference) === canonical(reference);
}

export function seededSpecification(record: typeof golden.specifications[number]): Specification {
  return { ...specificationView(record.payload), sha256: record.sha256,
    status: record.approval ? "approved" : "draft", approval: record.approval, unresolved_fields: record.unresolved_fields };
}
