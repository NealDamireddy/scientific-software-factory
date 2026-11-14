// Browser-local contract fixture. No method in this adapter contacts a service,
// acquires a measurement, or evaluates scientific source.
import demo from "../../fixtures/context/demo.json";
import { accessError, WorkspaceError } from "./api";
import type {
  Calibration,
  FieldErrors,
  FixtureFault,
  Lab,
  Pin,
  Project,
  Revision,
  Snapshot,
  SpecInput,
  Specification,
  WorkspaceClient,
} from "./api";
import { queuedRun, recordedAt, recordedRuns } from "./fixture-runs";

const prefix = "evolve.workspace.fixture.v1/";
type Store = { snapshot: Snapshot; submissions: { key: string; digest: string; run_id: string }[] };
const current = <T>(items: T[]) => items[items.length - 1];

function field(key: string, reason: string): never {
  throw new WorkspaceError(422, "Review the highlighted fields.", { [key]: reason }, "invalid_fields");
}
function compare(actual: number, expected: number) {
  if (actual !== expected)
    throw new WorkspaceError(
      409,
      "Revision conflict. Reopen the current revision before retrying.",
      {},
      "conflict",
    );
}
function pin(record: Pin): Pin {
  const { lab_id, project_id, revision, sha256 } = record;
  return { lab_id, project_id, revision, sha256 };
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") {
    return (
      "{" +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, val]) => JSON.stringify(key) + ":" + canonical(val))
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}
async function digest(value: unknown) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)));
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}
async function revision<T extends Lab | Project>(
  payload: T,
  number: number,
  lab?: Pin,
): Promise<Revision<T>> {
  return {
    lab_id: payload.lab_id,
    project_id: "project_id" in payload ? payload.project_id : null,
    revision: number,
    sha256: await digest(payload),
    payload,
    lab_revision: lab?.revision ?? null,
    lab_sha256: lab?.sha256 ?? null,
  };
}
function confirmationFields(spec: SpecInput) {
  return [
    "experiment_type",
    "settings",
    "sample_ids",
    "units",
    "outputs",
    "validation_criteria",
    ...(spec.standards.length ? ["standards"] : []),
    ...(spec.calibration ? ["calibration"] : []),
    ...(spec.schedule ? ["schedule"] : []),
  ].sort();
}
async function draft(input: SpecInput, specification_id: string, revision: number): Promise<Specification> {
  const payload = { ...input, specification_id, revision, lab: pin(input.lab), project: pin(input.project) };
  return { ...payload, sha256: await digest(payload), status: "draft", approval: null };
}
function approved(spec: Specification, at: string): Specification {
  return {
    ...spec,
    status: "approved",
    approval: {
      actor: "Fixture researcher",
      approved_at: at,
      confirmed_fields: confirmationFields(spec),
      specification_sha256: spec.sha256,
    },
  };
}

async function seed(projectId: string): Promise<Store> {
  const lab = await revision(demo.lab, 1);
  const project = await revision({ ...demo.project, project_id: projectId }, 1, lab);
  const instrument = lab.payload.instruments[0];
  const calibrationBody = {
    id: "cal-visible-01",
    contract: "absorbance-linear@1",
    settings: { wavelength_nm: 650, path_length_mm: 10 },
    unit: "mg/L",
    instrument_id: instrument.instrument_id,
    profile_sha256: instrument.profile_sha256,
    blank_id: "blank-101",
  };
  const calibration: Calibration = { ...calibrationBody, sha256: await digest(calibrationBody) };
  const snapshot: Snapshot = {
    project_id: projectId,
    recorded_at: recordedAt,
    labs: [lab],
    projects: [project],
    calibrations: [],
    specifications: [],
    runs: [],
  };
  if (projectId === "visible-assay") {
    const base: SpecInput = {
      lab: pin(lab),
      project: pin(project),
      instrument,
      experiment_type: "concentration",
      sample_ids: demo.project.sample_ids,
      standards: demo.project.standards,
      calibration: null,
      schedule: null,
      units: demo.project.units,
      settings: demo.project.measurement_settings,
      validation_criteria: demo.project.validation_criteria,
      outputs: ["calibration_id", "sample_id", "concentration_mg_l", "replicate_sd_mg_l", "review_reason"],
    };
    const concentration = approved(await draft(base, "spec-concentration", 1), "2026-11-12T08:59:45Z");
    const course = approved(
      await draft(
        {
          ...base,
          experiment_type: "time_course",
          standards: [],
          calibration,
          schedule: { interval_s: 30, point_count: 2 },
          outputs: [...base.outputs, "timestamp"],
        },
        "spec-time-course",
        1,
      ),
      "2026-11-12T09:04:45Z",
    );
    snapshot.specifications.push(concentration, course);
    snapshot.calibrations.push(calibration);
    snapshot.runs = recordedRuns(concentration, course);
  }
  return { snapshot, submissions: [] };
}

// These checks model the editable fixture responses only. The live client
// submits the researcher's inputs to the service for authoritative validation.
function checkSpec(input: SpecInput, state: Snapshot) {
  const fields: FieldErrors = {};
  const project = current(state.projects);
  const lab = state.labs.find(
    (item) => item.revision === project.lab_revision && item.sha256 === project.lab_sha256,
  );
  if (
    input.project.sha256 !== project.sha256 ||
    input.project.revision !== project.revision ||
    input.project.project_id !== state.project_id ||
    !lab ||
    input.lab.lab_id !== lab.lab_id ||
    input.lab.revision !== lab.revision ||
    input.lab.sha256 !== lab.sha256
  ) {
    throw new WorkspaceError(
      409,
      "Context revisions changed. Reopen the current project revision.",
      {},
      "conflict",
    );
  }
  if (
    !lab.payload.instruments.some((i) => canonical(i) === canonical(input.instrument)) ||
    input.instrument.instrument_id !== project.payload.instrument_id
  )
    fields.instrument = "Select the instrument pinned to this project revision.";
  if (!["concentration", "time_course"].includes(input.experiment_type))
    fields.experiment_type = "Unsupported experiment type.";
  if (![450, 550, 650].includes(input.settings.wavelength_nm ?? 0))
    fields["settings.wavelength_nm"] = "Select 450, 550 or 650 nm.";
  if (input.settings.path_length_mm !== 10)
    fields["settings.path_length_mm"] = "The profile requires a 10 mm path length.";
  if (
    !Number.isInteger(input.settings.replicates) ||
    input.settings.replicates < 1 ||
    input.settings.replicates > 10
  )
    fields["settings.replicates"] = "Select 1–10 replicates.";
  if (!input.sample_ids.length || input.sample_ids.some((id) => !id.trim()))
    fields.sample_ids = "Provide the sample identifiers.";
  if (
    input.experiment_type === "concentration" &&
    new Set(
      input.standards
        .filter((s) => s.sample_id && s.known_concentration > 0)
        .map((s) => s.known_concentration),
    ).size < 3
  )
    fields.standards = "Provide three distinct positive standard levels.";
  if (input.experiment_type === "time_course") {
    const calibration = state.calibrations.find((c) => canonical(c) === canonical(input.calibration));
    if (!calibration) fields.calibration = "Select a saved calibration.";
    else if (
      calibration.settings.wavelength_nm !== input.settings.wavelength_nm ||
      calibration.settings.path_length_mm !== input.settings.path_length_mm ||
      calibration.unit !== input.units.concentration ||
      calibration.instrument_id !== input.instrument.instrument_id ||
      calibration.profile_sha256 !== input.instrument.profile_sha256
    )
      fields.calibration = "The calibration requires matching units, instrument and optical settings.";
    if (
      !input.schedule ||
      !Number.isFinite(input.schedule.interval_s) ||
      input.schedule.interval_s < 1 ||
      input.schedule.interval_s > 3600
    )
      fields["schedule.interval_s"] = "Confirm an interval of 1–3600 seconds.";
    if (
      !input.schedule ||
      !Number.isInteger(input.schedule.point_count) ||
      input.schedule.point_count < 2 ||
      input.schedule.point_count > 100
    )
      fields["schedule.point_count"] = "Confirm a point count of 2–100.";
  }
  if (canonical(input.units) !== canonical(project.payload.units))
    fields.units = "Confirm the units from the project protocol.";
  if (!input.outputs.length) fields.outputs = "Confirm expected outputs.";
  if (!input.validation_criteria.length) fields.validation_criteria = "Confirm validation criteria.";
  if (Object.keys(fields).length)
    throw new WorkspaceError(422, "Review the highlighted fields.", fields, "invalid_fields");
}

let next: Promise<unknown> = Promise.resolve();
function serialized<T>(operation: () => Promise<T>): Promise<T> {
  const result = next.then(operation, operation);
  next = result.catch(() => {});
  return result;
}

export function createFixtureClient(
  options: { fault?: () => FixtureFault | undefined } = {},
): WorkspaceClient {
  let ended = false;
  function check(projectId: string) {
    const fault = options.fault?.();
    if (ended || fault === "unauthenticated" || fault === "expired") throw accessError(401, fault);
    if (fault === "forbidden" || !["visible-assay", "empty-assay"].includes(projectId))
      throw accessError(403);
    if (fault === "unavailable") throw new WorkspaceError(503, "Workspace service unavailable. Try again.");
  }
  function withStore<T>(projectId: string, write: boolean, fn: (store: Store) => T | Promise<T>): Promise<T> {
    return serialized(async () => {
      check(projectId);
      const raw = sessionStorage.getItem(prefix + projectId);
      const state: Store = raw ? JSON.parse(raw) : await seed(projectId);
      const result = await fn(state);
      check(projectId);
      if (write || !raw) sessionStorage.setItem(prefix + projectId, JSON.stringify(state));
      return result;
    });
  }
  return {
    read: (projectId) => withStore(projectId, false, ({ snapshot }) => snapshot),
    saveLab: (id, payload, expected) =>
      withStore(id, true, async ({ snapshot }) => {
        const latest = current(snapshot.labs);
        compare(latest.revision, expected);
        if (latest.lab_id !== payload.lab_id) field("lab_id", "Use the lab assigned to this workspace.");
        if (!payload.name.trim()) field("name", "Enter the lab name.");
        if (
          !payload.instruments.length ||
          payload.instruments.some(
            (i) =>
              !i.instrument_id ||
              i.lab_id !== payload.lab_id ||
              i.profile_id !== demo.lab.instruments[0].profile_id ||
              i.profile_sha256 !== demo.lab.instruments[0].profile_sha256,
          )
        )
          field("instruments", "Select a registered profile and instrument belonging to this lab.");
        if (!payload.approved_libraries.length) field("approved_libraries", "Enter the approved libraries.");
        if (!payload.operating_restrictions.length)
          field("operating_restrictions", "Enter operating restrictions.");
        const nextLab = await revision(payload, expected + 1);
        snapshot.labs.push(nextLab);
        return nextLab;
      }),
    saveProject: (id, payload, expected) =>
      withStore(id, true, async ({ snapshot }) => {
        compare(current(snapshot.projects).revision, expected);
        const lab = current(snapshot.labs);
        if (payload.project_id !== id) field("project_id", "Use the selected workspace project.");
        if (payload.lab_id !== lab.lab_id) field("lab_id", "Select the lab assigned to this project.");
        if (!lab.payload.instruments.some((i) => i.instrument_id === payload.instrument_id))
          field("instrument_id", "Select an instrument owned by this lab.");
        for (const key of ["scientific_objective", "protocol_id", "analysis_method"] as const)
          if (!payload[key].trim()) field(key, "Enter a value.");
        if (!Number.isInteger(payload.protocol_revision) || payload.protocol_revision < 1)
          field("protocol_revision", "Enter a positive protocol revision.");
        if (!payload.validation_criteria.length) field("validation_criteria", "Enter validation criteria.");
        for (const key of ["concentration", "wavelength", "path_length"] as const)
          if (!payload.units[key]?.trim()) field("units." + key, "Enter units.");
        const record = await revision(payload, expected + 1, lab);
        snapshot.projects.push(record);
        return record;
      }),
    saveSpecification: (id, payload, expected) =>
      withStore(id, true, async ({ snapshot }) => {
        const prior = snapshot.specifications.filter(
          (spec) => spec.specification_id === payload.specification_id,
        );
        compare(current(prior)?.revision ?? 0, expected);
        checkSpec(payload, snapshot);
        const record = await draft(payload, payload.specification_id || crypto.randomUUID(), expected + 1);
        snapshot.specifications.push(record);
        return record;
      }),
    approve: (id, spec, confirmed) =>
      withStore(id, true, ({ snapshot }) => {
        const latest = current(
          snapshot.specifications.filter((s) => s.specification_id === spec.specification_id),
        );
        if (!latest || latest.sha256 !== spec.sha256 || latest.revision !== spec.revision)
          throw new WorkspaceError(409, "The specification revision changed.");
        if (latest.approval) return latest;
        if (canonical([...confirmed].sort()) !== canonical(confirmationFields(latest)))
          field("confirmation", "Confirm every scientific field on this revision.");
        const record = approved(latest, recordedAt);
        snapshot.specifications[snapshot.specifications.indexOf(latest)] = record;
        return record;
      }),
    submit: (id, spec, key) =>
      withStore(id, true, ({ snapshot, submissions }) => {
        const saved = snapshot.specifications.find(
          (s) => s.sha256 === spec.sha256 && s.specification_id === spec.specification_id,
        );
        if (!saved?.approval || saved.approval.specification_sha256 !== saved.sha256)
          field("approval", "Approve this exact specification revision.");
        const prior = submissions.find((submission) => submission.key === key);
        if (prior && prior.digest !== saved.sha256)
          throw new WorkspaceError(409, "Submission key already used for another revision.");
        if (prior) return { run_id: prior.run_id };
        const run = queuedRun("fixture-" + crypto.randomUUID(), saved, recordedAt);
        snapshot.runs.push(run);
        submissions.push({ key, digest: saved.sha256, run_id: run.run_id });
        return { run_id: run.run_id };
      }),
    evidence: (id, runId) =>
      withStore(id, false, ({ snapshot }) => {
        const run = snapshot.runs.find((item) => item.run_id === runId);
        if (!run) throw new WorkspaceError(404, "Evidence is unavailable.");
        const report = {
          mode: "fixture",
          project_id: id,
          incomplete: run.acquisition !== "completed",
          run,
          specification: snapshot.specifications.find((s) => s.sha256 === run.spec_digest),
        };
        return new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      }),
    async endSession() {
      ended = true;
      await serialized(async () => {
        for (const id of ["visible-assay", "empty-assay"]) sessionStorage.removeItem(prefix + id);
      });
    },
  };
}
