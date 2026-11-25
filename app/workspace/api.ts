// Public projections supplied by the authorized workspace API. The browser never
// receives worker receipts containing credentials or simulator-private samples.
export type Mode = "fixture" | "live";
export type ExperimentType = "concentration" | "time_course";
// WO-8 contract_outputs, projected for review before the first draft is saved.
export function contractOutputs(kind: ExperimentType): string[] {
  const fields = ["calibration_id", "sample_id", "concentration_mg_l", "replicate_sd_mg_l", "review_reason"];
  return kind === "time_course" ? [...fields, "timestamp"] : fields;
}
export type Instrument = {
  lab_id: string;
  instrument_id: string;
  profile_id: string;
  profile_sha256: string;
};
export type Lab = {
  schema_version: number;
  lab_id: string;
  name: string;
  instruments: Instrument[];
  approved_libraries: string[];
  operating_restrictions: string[];
};
export type Units = { concentration: string; wavelength: string; path_length: string };
export type Standard = { sample_id: string; known_concentration: number };
export type Settings = {
  operation: string;
  wavelength_nm: number | null;
  path_length_mm: number;
  replicates: number;
};
export type Project = {
  schema_version: number;
  project_id: string;
  lab_id: string;
  instrument_id: string;
  scientific_objective: string;
  protocol_id: string;
  protocol_revision: number;
  units: Units;
  analysis_method: string;
  validation_criteria: string[];
  sample_ids?: string[];
  standards?: Standard[];
  measurement_settings?: Settings;
};
export type Pin = { revision: number; sha256: string; lab_id: string; project_id: string | null };
export type Revision<T> = Pin & { payload: T; lab_revision: number | null; lab_sha256: string | null };
export type Calibration = {
  id: string;
  sha256: string;
  contract: string;
  settings: { wavelength_nm: number; path_length_mm: number };
  unit: string;
  instrument_id: string;
  profile_sha256: string;
  blank_id: string;
};
export type SpecInput = {
  specification_id?: string;
  lab: Pin;
  project: Pin;
  instrument: Instrument;
  experiment_type: ExperimentType;
  sample_ids: string[];
  standards: { sample_id: string; known_concentration: number | null }[];
  calibration: Calibration | null;
  settings: Omit<Settings, "replicates" | "path_length_mm"> & {replicates: number | null; path_length_mm: number | null};
  schedule: { interval_s: number | null; point_count: number | null } | null;
  units: Units;
  outputs: string[];
  validation_criteria: string[];
};
export type Approval = {
  actor: string;
  approved_at: string;
  confirmed_fields: string[];
  specification_sha256: string;
};
export type Specification = SpecInput & {
  specification_id: string;
  revision: number;
  sha256: string;
  status: "draft" | "approved";
  approval: Approval | null;
  unresolved_fields?: FieldErrors;
};
export type ResultRow = {
  sample_id: string;
  concentration_mg_l: number | null;
  replicate_sd_mg_l: number | null;
  review_reason: string | null;
  timestamp?: string | null;
  elapsed_s?: number | null;
};
export type Run = {
  run_id: string;
  job_id: string | null;
  experiment_type: ExperimentType;
  spec_digest: string;
  approval: string;
  recipe: string;
  software: string;
  acquisition: string;
  analysis: string;
  blockers: string[];
  submitted_at: string;
  software_started_at: string | null;
  software_finished_at: string | null;
  acquisition_started_at: string | null;
  acquisition_finished_at: string | null;
  analysis_started_at: string | null;
  analysis_finished_at: string | null;
  software_wait_s: number | null;
  software_wait_pending: boolean;
  preparation: "reuse" | "revision" | "generation" | null;
  release_id: string | null;
  source_revision: string | null;
  provenance: "simulated" | "archive" | "replay";
  result: { calibration_id: string; unit: string; results: ResultRow[] } | null;
  scientific_review: string;
};
// Mirrors the factory's gates: a result is shown only for a run whose
// software is ready, whose recipe is verified, that has no open blockers, and
// that is pinned to a release and source revision.
export function verifiedResult(run: Run) {
  return run.acquisition === "completed" && run.analysis === "completed" &&
    run.software === "ready" && run.recipe === "verified" &&
    Array.isArray(run.blockers) && run.blockers.length === 0 &&
    run.release_id && run.source_revision ? run.result : null;
}

// An approval counts only when it pins this exact specification revision.
export function approvalMatches(spec: Pick<Specification, "sha256" | "approval"> | null | undefined) {
  return !!spec?.approval && spec.approval.specification_sha256 === spec.sha256;
}

export type Snapshot = {
  project_id: string;
  recorded_at: string;
  labs: Revision<Lab>[];
  projects: Revision<Project>[];
  specifications: Specification[];
  calibrations: Calibration[];
  runs: Run[];
};
export type FieldErrors = Record<string, string>;
export class WorkspaceError extends Error {
  constructor(
    public status: number,
    message: string,
    public fields: FieldErrors = {},
    public code = "",
  ) {
    super(message);
  }
  get accessDenied() {
    return this.status === 401 || this.status === 403;
  }
}
export interface WorkspaceClient {
  read(projectId: string): Promise<Snapshot>;
  saveLab(projectId: string, payload: Lab, expectedRevision: number): Promise<Revision<Lab>>;
  saveProject(projectId: string, payload: Project, expectedRevision: number): Promise<Revision<Project>>;
  saveSpecification(projectId: string, payload: SpecInput, expectedRevision: number): Promise<Specification>;
  approve(projectId: string, spec: Specification, confirmedFields: string[]): Promise<Specification>;
  submit(projectId: string, spec: Specification, submissionKey: string): Promise<{ run_id: string }>;
  evidence(projectId: string, runId: string): Promise<Blob>;
  endSession(): Promise<void>;
}

export type FixtureFault = "unauthenticated" | "expired" | "forbidden" | "unavailable";
export function accessError(status: number, code?: string) {
  if (status === 403) return new WorkspaceError(403, "Access to this project was denied.", {}, "forbidden");
  if (code === "expired" || code === "expired_session" || code === "session_expired")
    return new WorkspaceError(401, "Your session has expired. Sign in again.", {}, "expired");
  return new WorkspaceError(401, "Sign in to access this workspace.", {}, "unauthenticated");
}

type ErrorBody = { code?: string; message?: string; fields?: FieldErrors };
const unavailable = () => new WorkspaceError(503, "Workspace service unavailable. Try again.");
const invalidResponse = () => new WorkspaceError(502, "The workspace service returned an invalid response.");

function segment(id: string) {
  if (!id || id === "." || id === "..") throw new WorkspaceError(422, "Invalid workspace record identifier.");
  return encodeURIComponent(id);
}

export function createLiveClient(baseUrl = ""): WorkspaceClient {
  const base = baseUrl.replace(/\/+$/, "");
  async function request(path: string, projectId?: string, body?: unknown) {
    const query = projectId === undefined ? "" : "?project_id=" + encodeURIComponent(projectId);
    let response: Response;
    try {
      response = await fetch(base + "/v1/" + path + query, {
        method: body === undefined ? "GET" : "POST",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(12000),
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw unavailable();
    }
    if (response.ok) return response;
    const problem: ErrorBody = (await response.json().catch(() => ({}))) || {};
    if (response.status === 401 || response.status === 403) throw accessError(response.status, problem.code);
    if (response.status >= 500) throw unavailable();
    if (response.status === 409)
      throw new WorkspaceError(
        409,
        "Revision conflict. Reopen the current revision before retrying.",
        {},
        "conflict",
      );
    if (response.status === 400 || response.status === 422) {
      const fields = Object.fromEntries(
        Object.entries(problem.fields || {}).filter(([, value]) => typeof value === "string"),
      );
      throw new WorkspaceError(response.status, "Review the fields and try again.", fields, problem.code);
    }
    throw new WorkspaceError(response.status, "The workspace request could not be completed.");
  }
  async function json<T>(path: string, projectId: string, body?: unknown): Promise<T> {
    const response = await request(path, projectId, body);
    try {
      return await response.json();
    } catch {
      throw invalidResponse();
    }
  }
  return {
    async read(projectId) {
      const data = await json<Snapshot>("projects/" + segment(projectId) + "/workspace", projectId);
      if (data?.project_id !== projectId) throw accessError(403);
      if (
        typeof data.recorded_at !== "string" ||
        ![data.labs, data.projects, data.specifications, data.runs, data.calibrations].every(Array.isArray)
      )
        throw invalidResponse();
      return data;
    },
    saveLab: (projectId, payload, expected_revision) =>
      json("labs", projectId, { payload, expected_revision }),
    saveProject: (projectId, payload, expected_revision) =>
      json("projects", projectId, { payload, expected_revision }),
    saveSpecification: (projectId, payload, expected_revision) =>
      json("specifications", projectId, { payload, expected_revision }),
    approve: (projectId, spec, confirmed_fields) =>
      json("specifications/" + segment(spec.specification_id) + "/approve", projectId, {
        expected_revision: spec.revision,
        specification_sha256: spec.sha256,
        confirmed_fields,
      }),
    submit: (projectId, spec, idempotency_key) =>
      json("runs", projectId, {
        specification_sha256: spec.sha256,
        instrument_id: spec.instrument.instrument_id,
        idempotency_key,
      }),
    async evidence(projectId, runId) {
      const response = await request("runs/" + segment(runId) + "/evidence", projectId);
      // The authorized route streams the artifact. Refuse a sign-in page or an empty success.
      if (response.status === 204 || response.headers.get("Content-Type")?.includes("text/html"))
        throw invalidResponse();
      const artifact = await response.blob();
      if (!artifact.size) throw invalidResponse();
      return artifact;
    },
    async endSession() {
      await request("session/logout", undefined, {});
    },
  };
}
