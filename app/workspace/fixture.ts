// Browser-local contract fixture. No method in this adapter contacts a service,
// acquires a measurement, or evaluates scientific source.
import demo from "../../fixtures/context/demo.json";
import { contractOutputs, accessError, WorkspaceError } from "./api";
import type {
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
import { canonical, digest, golden, matchesFrozenCalibration, pin, seededSpecification, sessionSpec, specificationView } from "./fixture-provenance";
import type { ContextRecord, SpecRecord } from "./fixture-provenance";
import { queuedRun, recordedAt, recordedRuns } from "./fixture-runs";

const prefix = "evolve.workspace.fixture.v2/";
type Store = { snapshot: Snapshot; specification_records: Record<string, SpecRecord>; submissions: { key: string; digest: string; run_id: string }[] };
const current = <T>(items: T[]) => items[items.length - 1];

function field(key: string, reason: string): never {
  throw new WorkspaceError(422, "Review the highlighted fields.", { [key]: reason }, "invalid_fields");
}
const contextIdentifier = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
function checkTextList(key: string, values: string[]) {
  if (values.some((value) => !value.trim()) || new Set(values).size !== values.length)
    field(key, "Enter distinct, nonblank values.");
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
async function revision<T extends Lab | Project>(
  payload: T,
  number: number,
  lab?: Pin,
): Promise<ContextRecord<T>> {
  return {
    revision_id: crypto.randomUUID(),
    kind: "project_id" in payload ? "project" : "lab",
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
async function draft(input: SpecInput, specification_id: string, revision: number, store: Store): Promise<Specification> {
  // checkProtectedFields has already resolved and validated both exact pins.
  const project = store.snapshot.projects.find(p => p.revision === input.project.revision)!;
  const lab = store.snapshot.labs.find(l => l.revision === input.lab.revision)!;
  const payload = sessionSpec(input, specification_id, revision, lab, project);
  const sha256 = await digest(payload);
  store.specification_records[sha256] = { origin: "fixture-session", payload };
  return { ...specificationView(payload), sha256, status: "draft", approval: null };
}

// WO-8 resolves and verifies the immutable record each time its identity
// authorizes an operation. Session storage also contains a separate UI view.
async function resolveRecord(store: Store, sha256: string) {
  const view = store.snapshot.specifications.find(s => s.sha256 === sha256);
  const record = store.specification_records[sha256];
  const captured = golden.specifications.find(s => s.sha256 === sha256);
  const invalid = () => new WorkspaceError(409, "Stored specification differs from its pinned record.", {}, "conflict");
  if (!view || !record || !record.payload ||
      (captured ? record.origin !== "producer" || canonical(record.payload) !== canonical(captured.payload)
                : record.origin !== "fixture-session" || await digest(record.payload) !== sha256)) throw invalid();
  const { sha256: _identity, approval, status, unresolved_fields: _issues, ...projected } = view;
  if (canonical(projected) !== canonical(specificationView(record.payload)) ||
      status !== (approval ? "approved" : "draft") ||
      (approval && approval.specification_sha256 !== sha256) ||
      (captured && canonical(approval) !== canonical(captured.approval))) throw invalid();
  return {view, record};
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
  const lab = structuredClone(golden.lab);
  const project = projectId === golden.project.project_id ? structuredClone(golden.project)
    : await revision({ ...demo.project, project_id: projectId }, 1, lab);
  const specification_records: Record<string, SpecRecord> = {};
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
    for (const source of golden.specifications) {
      const record = structuredClone(source);
      specification_records[record.sha256] = { origin: "producer", payload: record.payload };
      snapshot.specifications.push(seededSpecification(record));
    }
    snapshot.calibrations.push(structuredClone(golden.calibration.reference));
    const ready = snapshot.specifications.filter(spec => spec.status === "approved");
    snapshot.runs = recordedRuns(ready[0], ready[1]);
  }
  return { snapshot, specification_records, submissions: [] };
}

// Sample and standard IDs share the acquisition contract's namespace.
function checkSamples(input: SpecInput, fields: FieldErrors) {
  const identifier = /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/;
  const ids = new Set(input.sample_ids);
  if (
    !ids.size ||
    ids.size !== input.sample_ids.length ||
    input.sample_ids.some((id) => !identifier.test(id))
  )
    fields.sample_ids = "Select distinct opaque sample identifiers.";
  const levels = new Set<number>();
  for (const { sample_id, known_concentration } of input.standards) {
    if (
      !identifier.test(sample_id) ||
      ids.has(sample_id) ||
      !Number.isFinite(known_concentration) ||
      known_concentration === null ||
      known_concentration <= 0
    ) {
      fields.standards =
        "Use distinct standard IDs, separate from unknowns, with finite positive known levels.";
      return;
    }
    ids.add(sample_id);
    levels.add(known_concentration);
  }
  if (input.experiment_type === "concentration" && levels.size < 3)
    fields.standards = "Provide three distinct positive standard levels.";
  if (ids.size > 100) fields.sample_ids = "Acquisition supports at most 100 combined samples and standards.";
}

// These checks model the editable fixture responses only. The live client
// submits the researcher's inputs to the service for authoritative validation.
function checkProtectedFields(input: SpecInput, state: Snapshot) {
  const fields: FieldErrors = {};
  const first = state.specifications.find((item) => item.specification_id === input.specification_id);
  if (first && (canonical(input.project) !== canonical(first.project) ||
      canonical(input.lab) !== canonical(first.lab) || canonical(input.instrument) !== canonical(first.instrument))) {
    throw new WorkspaceError(409, "Start a new specification to use different context.", {}, "conflict");
  }

  const project = state.projects.find((item) => canonical(pin(item)) === canonical(input.project));
  if (!project || project.project_id !== state.project_id)
    throw new WorkspaceError(409, "Pinned project revision is unavailable.", {}, "conflict");
  const lab = state.labs.find((item) => item.lab_id === project.lab_id &&
    item.revision === project.lab_revision && item.sha256 === project.lab_sha256);
  if (!lab || canonical(pin(lab)) !== canonical(input.lab))
    throw new WorkspaceError(409, "Lab pin differs from the selected project revision.", {}, "conflict");
  const instrument = lab.payload.instruments.find((item) => item.instrument_id === project.payload.instrument_id);
  if (!instrument || canonical(instrument) !== canonical(input.instrument))
    fields.instrument = "Select the instrument pinned to this project revision.";
  if (canonical(input.units) !== canonical(project.payload.units))
    fields.units = "Confirm the units from the project protocol.";
  if (canonical(input.outputs) !== canonical(contractOutputs(input.experiment_type)))
    fields.outputs = "Expected outputs are defined by the experiment contract.";
  if (canonical(input.validation_criteria) !== canonical(project.payload.validation_criteria))
    fields.validation_criteria = "Use the validation criteria from the pinned project revision.";
  if (Object.keys(fields).length)
    throw new WorkspaceError(422, "Review the highlighted fields.", fields, "invalid_fields");
}

function scientificIssues(input: SpecInput, state: Snapshot): FieldErrors {
  const fields: FieldErrors = {};
  if (!["concentration", "time_course"].includes(input.experiment_type))
    fields.experiment_type = "Unsupported experiment type.";
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(input.instrument.instrument_id))
    fields["instrument.instrument_id"] = "Use an instrument ID of at most 200 valid characters.";
  if (input.settings.operation !== "measure-absorbance")
    fields["settings.operation"] = "Use the registered absorbance measurement operation.";
  if (![450, 550, 650].includes(input.settings.wavelength_nm ?? 0))
    fields["settings.wavelength_nm"] = "Select 450, 550 or 650 nm.";
  if (input.settings.path_length_mm !== 10)
    fields["settings.path_length_mm"] = "The profile requires a 10 mm path length.";
  if (
    !Number.isInteger(input.settings.replicates) ||
    input.settings.replicates === null ||
    input.settings.replicates < 1 ||
    input.settings.replicates > 10
  )
    fields["settings.replicates"] = "Select 1–10 replicates.";
  checkSamples(input, fields);
  if (input.calibration || input.experiment_type === "time_course") {
    const calibration = state.calibrations.find((c) => canonical(c) === canonical(input.calibration));
    if (!calibration || !matchesFrozenCalibration(calibration, input)) fields.calibration = "Select a saved calibration.";
    else if (
      calibration.settings.wavelength_nm !== input.settings.wavelength_nm ||
      calibration.settings.path_length_mm !== input.settings.path_length_mm ||
      calibration.unit !== input.units.concentration ||
      calibration.instrument_id !== input.instrument.instrument_id ||
      calibration.profile_sha256 !== input.instrument.profile_sha256
    )
      fields.calibration = "The calibration requires matching units, instrument and optical settings.";
  }
  if (input.experiment_type === "time_course") {
    if (input.standards.length) fields.standards = "Remove standards to use the frozen time-course calibration.";
    if (
      !input.schedule ||
      !Number.isFinite(input.schedule.interval_s) ||
      input.schedule.interval_s === null ||
      input.schedule.interval_s < 1 ||
      input.schedule.interval_s > 3600
    )
      fields["schedule.interval_s"] = "Confirm an interval of 1–3600 seconds.";
    if (
      !input.schedule ||
      !Number.isInteger(input.schedule.point_count) ||
      input.schedule.point_count === null ||
      input.schedule.point_count < 2 ||
      input.schedule.point_count > 100
    )
      fields["schedule.point_count"] = "Confirm a point count of 2–100.";
  } else if (input.schedule !== null) {
    fields.schedule = "Schedules require a time-course specification.";
  }
  for (const [key, unit] of Object.entries(demo.project.units) as [keyof Project["units"], string][]) {
    if (input.units[key] !== unit) fields["units." + key] = "The v1 contract requires " + unit + ".";
  }
  return fields;
}

function requireReady(spec: Specification, state: Snapshot) {
  checkProtectedFields(spec, state);
  const fields = scientificIssues(spec, state);
  if (Object.keys(fields).length)
    throw new WorkspaceError(422, "Resolve the scientific fields before approval or submission.", fields, "invalid_fields");
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
        if (!payload.instruments.length) field("instruments", "Register at least one instrument.");
        const seen = new Set<string>();
        for (const [index, instrument] of payload.instruments.entries()) {
          const path = "instruments." + index + ".";
          if (!contextIdentifier.test(instrument.instrument_id))
            field(path + "instrument_id", "Use an instrument ID containing letters, digits, dots, underscores or hyphens.");
          if (seen.has(instrument.instrument_id))
            field(path + "instrument_id", "Duplicate instrument ID. Use a distinct ID for each instrument.");
          seen.add(instrument.instrument_id);
          if (instrument.lab_id !== payload.lab_id) field("instruments", "Select an instrument belonging to this lab.");
          if (instrument.profile_id !== demo.lab.instruments[0].profile_id)
            field(path + "profile_id", "Select the registered instrument profile.");
          if (instrument.profile_sha256 !== demo.lab.instruments[0].profile_sha256)
            field(path + "profile_sha256", "Use the registered profile digest.");
        }
        checkTextList("approved_libraries", payload.approved_libraries);
        checkTextList("operating_restrictions", payload.operating_restrictions);
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
        for (const key of ["scientific_objective", "analysis_method"] as const)
          if (!payload[key].trim()) field(key, "Enter a value.");
        if (!contextIdentifier.test(payload.protocol_id))
          field("protocol_id", "Use a protocol ID containing letters, digits, dots, underscores or hyphens.");
        if (!Number.isInteger(payload.protocol_revision) || payload.protocol_revision < 1)
          field("protocol_revision", "Enter a positive protocol revision.");
        if (!payload.validation_criteria.length) field("validation_criteria", "Enter validation criteria.");
        checkTextList("validation_criteria", payload.validation_criteria);
        for (const key of ["concentration", "wavelength", "path_length"] as const)
          if (!payload.units[key]?.trim()) field("units." + key, "Enter units.");
        const record = await revision(payload, expected + 1, lab);
        snapshot.projects.push(record);
        return record;
      }),
    saveSpecification: (id, payload, expected) =>
      withStore(id, true, async (store) => {
        const { snapshot } = store;
        const prior = snapshot.specifications.filter(
          (spec) => spec.specification_id === payload.specification_id,
        );
        if (payload.specification_id !== undefined && !prior.length)
          throw new WorkspaceError(404, "Specification is unavailable.");
        compare(current(prior)?.revision ?? 0, expected);
        checkProtectedFields(payload, snapshot);
        if (prior.length) await resolveRecord(store, current(prior).sha256);
        const record = await draft(payload, payload.specification_id || crypto.randomUUID(), expected + 1, store);
        record.unresolved_fields = scientificIssues(payload, snapshot);
        snapshot.specifications.push(record);
        return record;
      }),
    approve: (id, spec, confirmed) =>
      withStore(id, true, async store => {
        const { snapshot } = store;
        const saved = snapshot.specifications.find((row) =>
          row.specification_id === spec.specification_id && row.revision === spec.revision && row.sha256 === spec.sha256);
        if (!saved) throw new WorkspaceError(409, "Select the exact saved specification revision.");
        requireReady(saved, snapshot);
        await resolveRecord(store, saved.sha256);
        if (canonical([...confirmed].sort()) !== canonical(confirmationFields(saved)))
          field("confirmation", "Confirm every scientific field on this revision.");
        if (saved.approval) return saved;
        const record = approved(saved, recordedAt);
        snapshot.specifications[snapshot.specifications.indexOf(saved)] = record;
        return record;
      }),
    submit: (id, spec, key) =>
      withStore(id, true, async store => {
        const { snapshot, submissions } = store;
        const saved = snapshot.specifications.find(
          (s) => s.sha256 === spec.sha256 && s.specification_id === spec.specification_id,
        );
        if (!saved?.approval || saved.approval.specification_sha256 !== saved.sha256)
          field("approval", "Approve this exact specification revision.");
        requireReady(saved, snapshot);
        await resolveRecord(store, saved.sha256);
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
      withStore(id, false, async store => {
        const { snapshot } = store;
        const run = snapshot.runs.find((item) => item.run_id === runId);
        if (!run) throw new WorkspaceError(404, "Evidence is unavailable.");
        const {view: specification, record: specification_record} = await resolveRecord(store, run.spec_digest);
        if (!specification.approval) throw new WorkspaceError(409, "Run evidence has no pinned approval.");
        const ref = specification_record.payload.calibration;
        const calibration = (ref && matchesFrozenCalibration(ref, specification)) || run.result?.calibration_id === golden.calibration.reference.id
          ? golden.calibration : null;
        const report = {
          specification_record,
          calibration,
          mode: "fixture",
          project_id: id,
          incomplete: run.acquisition !== "completed",
          run,
          specification,
        };
        return new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      }),
    async endSession() {
      ended = true;
      await serialized(async () => {
        for (const id of ["visible-assay", "empty-assay"]) {
          sessionStorage.removeItem(prefix + id);
          sessionStorage.removeItem("evolve.workspace.fixture.v1/" + id);
        }
      });
    },
  };
}
