// Types shared by the sample client, the live client and the screens.
// Field names mirror Lab Factory's Python records (context.py, artifacts.py,
// workorders.py, checks.py). This file must stay free of runtime-only
// TypeScript syntax: it runs under Node type stripping.

export type Parameter = { name: string; unit: string; minimum: number; maximum: number };
export type Command = { name: string; required: string[]; optional: string[] };
export type Instrument = { id: string; name: string; model: string; firmware: string; notes: string;
                           parameters: Parameter[]; commands: Command[] };
export type Document = { id: string; kind: "sop" | "manual" | "standard" | "paper" | "note";
                         title: string; source: string; text: string };
export type Lab = { id: string; name: string; instruments: Instrument[]; documents: Document[] };
export type Project = { id: string; lab_id: string; title: string; goals: string;
                        documents: Document[] };
export type Experiment = { id: string; lab_id: string; project_id: string;
                           title: string; goal: string; instrument_ids: string[]; documents: Document[] };

export type Setting = { parameter: string; value: number; unit: string };
export type Action = { instrument_id: string; command: string; settings: Setting[] };
export type Amount = { what: string; value: number; unit: string };
export type ProcedureStep = { text: string; citations: string[]; action?: Action; amounts?: Amount[] };
export type CheckResult = { name: string; passed: boolean; detail: string };
export type WorkOrderStatus = "open" | "in_progress" | "in_review" | "released";

export type OutputKind = "procedure" | "run_plan" | "analysis_app" | "simulation";
export type Pin = { kind: "lab" | "project" | "experiment" | "skill"; id: string; revision: number; digest: string };
export type Revision = { number: number; digest: string; at: string; note: string };
export type WorkOrder = { id: string; experiment_id: string; kind: "procedure" | "run_plan"; objective: string;
                          status: WorkOrderStatus; released_submission: number | null; pins: Pin[] };
export type Submission = { work_order_id: string; number: number; artifact: unknown;
                           artifact_digest: string; results: CheckResult[]; passed: boolean; submitted_at: string };

export type RunStep = { command: string; settings: Setting[] };
export type RunPlan = { instrument_id: string; steps: RunStep[] };

// View models the factory supplies for display. The UI never computes these itself.
export type SettingView = { parameter: string; display: string;
                            canonical: { value: number; unit: string; minimum: number; maximum: number } };
export type StepView = { number: number; text: string; sources: { id: string; title: string }[];
                         settings: SettingView[]; unchecked: string[];
                         failures: CheckResult[] };
export type RunStepView = { number: number; instrument_id: string; command: string;
                            settings: SettingView[]; failures: CheckResult[] };
export type HistoryEvent = { event: "created" | "claimed" | "submitted" | "approved" | "rejected";
                             actor: string; submission: number | null; note: string; at: string };
export type OrderView<S> = { order: WorkOrder; submissions: Submission[]; shown: number; steps: S[];
                             history: HistoryEvent[];
                             /** Older orders of the same kind for the experiment, newest first. */
                             earlier?: { order: WorkOrder; submissions: Submission[]; history: HistoryEvent[] }[] };

export type ReferenceCase = { name: string; input: SyntheticParams; expect: { decay: boolean; rate_constant_per_s?: number };
                              rel_tol: number };
export type SyntheticParams = { k: number; a0: number; a_end: number; noise: number; seed: number;
                                step_s?: number; duration_s?: number };
export type AnalysisApp = { summary: string; code: string; entry: "analyze"; reference_cases: ReferenceCase[] };
export type Simulation = { title: string; summary: string; code: string; entry: "simulate";
                           x_label: string; y_label: string };

export type ActivityItem = { id: string; label: string; outcome: "done" | "passed" | "failed" | "info"; detail?: string };
export type OutputRef = { kind: OutputKind; work_order_id?: string; summary: string };
export type Proposal = { outputs: OutputKind[]; accepted: OutputKind[] | null };
export type Message = { id: string; from: "person" | "factory"; text: string; at: string; attachments?: string[];
                        proposal?: Proposal; activity?: ActivityItem[]; output_refs?: OutputRef[] };
export type Workspace = { experiment: Experiment; project: Project; messages: Message[];
                          procedure?: OrderView<StepView>; run_plan?: OrderView<RunStepView>;
                          analysis_app?: AnalysisApp; simulation?: Simulation };

export type SignOffRule = { mode: "anyone" } | { mode: "listed"; names: string[] };
export type LabSettings = { sign_off: SignOffRule };
export type SearchHit = { kind: "project" | "experiment" | "document" | "instrument" | "skill" | "connector";
                          id: string; title: string; href: string };

export type Skill = { id: string; title: string; description: string; body: string; enabled: boolean; revision: number };
export type ConnectorId = "google_drive" | "zotero" | "eln" | "instrument_folder" | "github";
export type ConnectorItem = { id: string; title: string; kind: Document["kind"] | "readings" | "code"; text: string };
export type Connector = { id: ConnectorId; name: string; provides: string; connected: boolean; account: string | null;
                          items: ConnectorItem[] };
export type McpTool = { name: string; description: string };
export type AgentSetup = { claude_code: string; codex_toml: string; cursor_json: string; tools: McpTool[]; skill_md: string };
export type AgentConnection = { worker: string; last_seen: string; work_order_ids: string[] };

export type Role = "researcher" | "approver";
export type AttentionItem = { kind: "sign_off" | "signed_off" | "rejected"; work_order_id: string; work_order_kind?: WorkOrder["kind"];
                              experiment_id: string; project_id: string; title: string };
export type DocumentTarget = { kind: "project" | "experiment"; id: string };
export type NewDocument = { title: string; kind: Document["kind"]; text: string };
export type OnActivity = (item: ActivityItem) => void;

export type ClientErrorCode = "not_found" | "invalid" | "refused";

export class ClientError extends Error {
  readonly code: ClientErrorCode;

  constructor(code: ClientErrorCode, message: string) {
    super(message);
    this.name = "ClientError";
    this.code = code;
  }
}

export interface LabFactoryClient {
  getLab(labId: string): Promise<Lab>;
  listProjects(labId: string): Promise<(Project & { experiments: Pick<Experiment, "id" | "title">[] })[]>;
  getProject(projectId: string): Promise<Project & { experiments: Experiment[] }>;
  createProject(labId: string, title: string, goals: string): Promise<Project>;
  createExperiment(projectId: string, description: string, instrumentIds: string[]): Promise<Experiment>;
  getWorkspace(experimentId: string): Promise<Workspace>;
  getSubmissionView(workOrderId: string, number: number): Promise<{ submission: Submission; steps: (StepView | RunStepView)[] }>;
  sendMessage(experimentId: string, text: string, attachments: File[], onActivity?: OnActivity): Promise<Message[]>;
  confirmPlan(experimentId: string, messageId: string, outputs: OutputKind[], onActivity?: OnActivity): Promise<Message[]>;
  approve(workOrderId: string, submission: number, person: string): Promise<WorkOrder>;
  reject(workOrderId: string, submission: number, person: string, reason: string): Promise<WorkOrder>;
  needsAttention(labId: string, role: Role): Promise<AttentionItem[]>;
  addDocument(target: DocumentTarget, doc: NewDocument): Promise<Revision>;
  listRevisions(kind: Pin["kind"], id: string): Promise<Revision[]>;
  getSettings(labId: string): Promise<LabSettings>;
  updateSettings(labId: string, settings: LabSettings): Promise<LabSettings>;
  search(labId: string, query: string): Promise<SearchHit[]>;
  listSkills(labId: string): Promise<Skill[]>;
  saveSkill(labId: string, skill: { id?: string; title: string; description: string; body: string }): Promise<Skill>;
  setSkillEnabled(labId: string, skillId: string, enabled: boolean): Promise<Skill>;
  listConnectors(labId: string): Promise<Connector[]>;
  connect(labId: string, connectorId: ConnectorId, account: string): Promise<Connector>;
  disconnect(labId: string, connectorId: ConnectorId): Promise<Connector>;
  importFromConnector(labId: string, connectorId: ConnectorId, itemId: string, target: DocumentTarget): Promise<Revision>;
  listAgentConnections(labId: string): Promise<AgentConnection[]>;
  getAgentSetup(labId: string): Promise<AgentSetup>;
}
