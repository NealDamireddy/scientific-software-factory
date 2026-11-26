// The sample conversation engine: the proposal a new experiment gets, the scripted build
// that confirming it plays out, and replies to messages and attachments. As in records.ts,
// everything that validates and claims (a proposal's `accepted`, an order id) does so in
// one synchronous block; only hashing, file reads and the pauses between activity items await.
import { canonicalDigest } from "../digest.ts";
import { ClientError } from "../types.ts";
import type {
  ActivityItem, AnalysisApp, CheckResult, Experiment, HistoryEvent, Instrument, Message, OnActivity, OutputKind,
  OutputRef, Pin, ProcedureStep, RunStepView, Simulation, StepView, Submission, WorkOrder,
} from "../types.ts";
import { ANALYSIS_CODE, SIMULATION_CODE } from "./code.ts";
import {
  procedureResults, procedureTemplate, procedureViews, referenceCases, runPlanResults, runPlanTemplate, runPlanViews,
} from "./content.ts";
import { enabledSkillPins, enabledSkills } from "./extensions.ts";
import * as records from "./records.ts";
import {
  addDocumentTo, appendMessage, copy, documentsFor, findExperiment, findProject, revisionKey, submissionsOf,
} from "./records.ts";
import type { SampleContext } from "./records.ts";
import type { SampleState } from "./seed.ts";

export type ActivityOptions = { onActivity?: OnActivity; stepMs?: number };

export const PROPOSAL_TEXT = "Here’s what I’d build for this experiment. Switch anything off you don’t need, then confirm.";
export const BUILT_TEXT = "Built. Everything passed its checks and is waiting for sign-off.";
const BUILT_WITH_FAILURES_TEXT = "Built. Some checks failed, so nothing is waiting for sign-off yet.";
export const SAMPLE_REPLY = "This is sample data, so the factory can’t act on that here. In the live app it would answer and update the outputs.";
export const ATTACHED_SOURCE = "Attached in the conversation";
const ATTACHMENT_LIMIT = 20_000;
const OUTPUT_ORDER: OutputKind[] = ["procedure", "run_plan", "analysis_app", "simulation"];

// The scripted Coomassie demo: attaching a file while WO-1 is the newest procedure rewrites it.
const COOMASSIE = "coomassie-run-1";
const COOMASSIE_ORDER = "WO-1";
// Coomassie rewrites in flight, per store, so two overlapping sends cannot both rewrite.
const rewriting = new WeakMap<SampleState, Set<string>>();

// ---------------------------------------------------------------- proposals

/** The outputs the factory offers for a description: always a procedure, then by keyword. */
export function proposeOutputs(description: string): OutputKind[] {
  const wanted = new Set<OutputKind>(["procedure"]);
  if (/run plan|automat|sequence|instrument control/i.test(description)) wanted.add("run_plan");
  if (/rate|kinetic|concentration|fit|analy|curve|quantif/i.test(description)) wanted.add("analysis_app");
  if (/simulat|model|predict/i.test(description)) wanted.add("simulation");
  return OUTPUT_ORDER.filter((kind) => wanted.has(kind));
}

/** Creates the experiment (revision 1), then opens its conversation with the person's description and a proposal. */
export async function createExperiment(
  ctx: SampleContext, projectId: string, description: string, instrumentIds: string[],
): Promise<Experiment> {
  const experiment = await records.createExperiment(ctx, projectId, description, instrumentIds);
  appendMessage(ctx, experiment.id, { from: "person", text: experiment.goal });
  appendMessage(ctx, experiment.id, {
    from: "factory", text: PROPOSAL_TEXT, proposal: { outputs: proposeOutputs(experiment.goal), accepted: null },
  });
  return experiment;
}

// ---------------------------------------------------------------- helpers

/** `Submission {n}, all checks passed` / `1 check failed` / `{k} checks failed`. */
function submissionSummary(number: number, results: CheckResult[]): string {
  const failed = results.filter((r) => !r.passed).length;
  if (failed === 0) return `Submission ${number}, all checks passed`;
  return `Submission ${number}, ${failed} ${failed === 1 ? "check" : "checks"} failed`;
}

function checksItem(results: CheckResult[]): Omit<ActivityItem, "id"> {
  const failed = results.filter((r) => !r.passed);
  if (results.length > 0 && failed.length === 0) return { label: `Ran ${results.length} checks: all passed`, outcome: "passed" };
  return {
    label: `Ran ${results.length} checks: ${failed.length} failed`, outcome: "failed",
    detail: failed.map((r) => `${r.name}: ${r.detail}`).join("; "),
  };
}

function latestRevision(state: SampleState, kind: Pin["kind"], id: string): { number: number; digest: string } {
  const revision = (state.revisions[revisionKey(kind, id)] ?? []).at(-1);
  if (!revision) throw new ClientError("not_found", `Unknown ${kind} ${id}.`);
  return revision;
}

/** Pins of the lab, project and experiment at their latest revisions, then each enabled skill. */
function currentPins(state: SampleState, experiment: Experiment): Pin[] {
  const pin = (kind: Pin["kind"], id: string): Pin => {
    const { number, digest } = latestRevision(state, kind, id);
    return { kind, id, revision: number, digest };
  };
  return [
    pin("lab", state.lab.id), pin("project", experiment.project_id), pin("experiment", experiment.id),
    ...enabledSkillPins(state),
  ];
}

/** New order ids are `WO-{n}`, one past the highest numbered order. */
function nextOrderId(state: SampleState): string {
  const taken = new Set(state.orders.map((o) => o.id));
  let n = 1 + Math.max(0, ...state.orders.map((o) => /^WO-(\d+)$/.exec(o.id)).map((m) => (m ? Number(m[1]) : 0)));
  while (taken.has(`WO-${n}`)) n += 1;
  return `WO-${n}`;
}

/** Plays activity items out: each is recorded and emitted, with `stepMs` between them. */
function activityLog(idPrefix: string, options: ActivityOptions) {
  const items: ActivityItem[] = [];
  const stepMs = options.stepMs ?? 0;
  return {
    items,
    async emit(item: Omit<ActivityItem, "id">): Promise<void> {
      if (items.length > 0 && stepMs > 0) await new Promise((resolve) => setTimeout(resolve, stepMs));
      const full: ActivityItem = { id: `${idPrefix}-a${items.length + 1}`, ...item };
      items.push(full);
      // The callback is only a UI notification: its failure must not strand the build.
      try {
        options.onActivity?.(copy(full));
      } catch {
        // ignored
      }
    },
  };
}

type OrderDraft = {
  experimentId: string; kind: WorkOrder["kind"]; objective: string; pins: Pin[];
  artifact: unknown; results: CheckResult[]; views: (StepView | RunStepView)[];
};

/**
 * Stores a work order with submission 1, its views and its history. The id is chosen
 * after the digest is computed, in the same synchronous block that stores the order.
 */
async function storeOrder(ctx: SampleContext, draft: OrderDraft): Promise<{ order: WorkOrder; submission: Submission }> {
  const digest = await canonicalDigest(draft.artifact);
  const { state } = ctx;
  const at = ctx.now().toISOString();
  const passed = draft.results.length > 0 && draft.results.every((r) => r.passed);
  const order: WorkOrder = {
    id: nextOrderId(state), experiment_id: draft.experimentId, kind: draft.kind, objective: draft.objective,
    status: passed ? "in_review" : "in_progress", released_submission: null, pins: draft.pins,
  };
  const submission: Submission = {
    work_order_id: order.id, number: 1, artifact: draft.artifact, artifact_digest: digest,
    results: draft.results, passed, submitted_at: at,
  };
  const history: HistoryEvent[] = [
    { event: "created", actor: "factory", submission: null, note: "", at },
    { event: "claimed", actor: "factory", submission: null, note: "", at },
    { event: "submitted", actor: "factory", submission: 1, note: passed ? "passed" : "failed", at },
  ];
  state.orders.push(order);
  state.submissions.push(submission);
  state.views[`${order.id}#1`] = draft.views;
  state.history[order.id] = history;
  return { order, submission };
}

function instrumentFor(state: SampleState, experiment: Experiment): Instrument {
  const instruments = state.lab.instruments;
  const chosen = instruments.find((i) => i.id === experiment.instrument_ids[0]) ?? instruments[0];
  if (!chosen) throw new ClientError("invalid", "This lab has no instruments to build for.");
  return chosen;
}

// ---------------------------------------------------------------- confirmPlan

function analysisApp(): AnalysisApp {
  return {
    summary: "Turns absorbance over time into a rate constant and half-life.",
    code: ANALYSIS_CODE,
    entry: "analyze",
    reference_cases: referenceCases(),
  };
}

function simulation(): Simulation {
  return {
    title: "Fading curves for three amounts of reducing agent",
    summary: "Predicted absorbance at the blue peak if the rate scales with the amount of reducing agent.",
    code: SIMULATION_CODE,
    entry: "simulate",
    x_label: "Time (s)",
    y_label: "Absorbance (AU)",
  };
}

/**
 * Accepts a proposal and builds the chosen outputs. Validation, the `accepted` flip and
 * every template are done synchronously, so a second confirmation is refused at once.
 */
export async function confirmPlan(
  ctx: SampleContext, experimentId: string, messageId: string, outputs: OutputKind[], options: ActivityOptions = {},
): Promise<Message[]> {
  const { state } = ctx;
  const experiment = findExperiment(state, experimentId);
  const project = findProject(state, experiment.project_id);
  const message = (state.messages[experimentId] ?? []).find((m) => m.id === messageId);
  if (!message) throw new ClientError("not_found", `Unknown message ${messageId}.`);
  const proposal = message.proposal;
  if (!proposal) throw new ClientError("invalid", "That message has no plan to confirm.");
  const chosen = new Set(outputs);
  if (chosen.size === 0 || [...chosen].some((kind) => !proposal.outputs.includes(kind))) {
    throw new ClientError("invalid", "Choose one or more of the proposed outputs.");
  }
  if (proposal.accepted !== null) throw new ClientError("refused", "This plan was already confirmed.");
  const accepted = proposal.outputs.filter((kind) => chosen.has(kind));

  // Everything the build needs, read now from the current context.
  const instrument = instrumentFor(state, experiment);
  const instruments = state.lab.instruments;
  const documents = documentsFor(state, experimentId);
  const pins = currentPins(state, experiment);
  const labRevision = pins[0].revision;
  const projectRevision = pins[1].revision;
  const drafts = new Map<OutputKind, OrderDraft>();
  if (chosen.has("procedure")) {
    const sop = state.lab.documents.find((d) => d.kind === "sop");
    const citations = [...(sop ? [sop.id] : []), ...project.documents.map((d) => d.id)];
    const steps = procedureTemplate(instrument, citations);
    const results = procedureResults(steps, documents, instruments, true);
    drafts.set("procedure", {
      experimentId, kind: "procedure", objective: `Write a procedure for “${experiment.title}”.`, pins: copy(pins),
      artifact: { steps }, results, views: procedureViews(steps, results, documents, instruments),
    });
  }
  if (chosen.has("run_plan")) {
    const plan = runPlanTemplate(instrument);
    const results = runPlanResults(plan, instruments);
    drafts.set("run_plan", {
      experimentId, kind: "run_plan", objective: `Write a run plan for “${experiment.title}”.`, pins: copy(pins),
      artifact: plan, results, views: runPlanViews(plan, results, instruments),
    });
  }
  proposal.accepted = accepted;

  const log = activityLog(messageId, options);
  const refs: OutputRef[] = [];
  let allPassed = true;
  await log.emit({ label: `Read lab context (revision ${labRevision})`, outcome: "done" });
  await log.emit({ label: `Read project context (revision ${projectRevision})`, outcome: "done" });
  for (const skill of enabledSkills(state)) await log.emit({ label: `Used skill: ${skill.title}`, outcome: "info" });
  for (const kind of accepted) {
    const draft = drafts.get(kind);
    if (draft) {
      const { order, submission } = await storeOrder(ctx, draft);
      await log.emit({ label: kind === "procedure" ? "Wrote procedure" : "Wrote run plan", outcome: "done" });
      await log.emit(checksItem(submission.results));
      allPassed &&= submission.passed;
      refs.push({ kind, work_order_id: order.id, summary: submissionSummary(1, submission.results) });
    } else if (kind === "analysis_app") {
      const app = analysisApp();
      state.apps[experimentId] = app;
      await log.emit({ label: "Wrote analysis app", outcome: "done" });
      await log.emit({ label: `Ran ${app.reference_cases.length} reference cases`, outcome: "info" });
      refs.push({ kind, summary: `Passes ${app.reference_cases.length} reference cases` });
    } else {
      const sim = simulation();
      state.simulations[experimentId] = sim;
      await log.emit({ label: "Wrote simulation", outcome: "done" });
      refs.push({ kind, summary: sim.title });
    }
  }
  const built = appendMessage(ctx, experimentId, {
    from: "factory", text: allPassed ? BUILT_TEXT : BUILT_WITH_FAILURES_TEXT, activity: log.items, output_refs: refs,
  });
  return [copy(built)];
}

// ---------------------------------------------------------------- sendMessage

/** `a`, `a and b`, `a, b and c`. */
function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function attachmentTitle(file: File): string {
  return file.name.trim() === "" ? "Attachment" : file.name.trim();
}

async function attachmentText(file: File): Promise<string> {
  const text = (await file.text()).slice(0, ATTACHMENT_LIMIT);
  return text.trim() === "" ? "(empty file)" : text;
}

/** Adds a file as an experiment document and returns the stored document's id. */
async function attach(ctx: SampleContext, experimentId: string, file: File): Promise<string> {
  const doc = { title: attachmentTitle(file), kind: "paper" as const, text: await attachmentText(file) };
  await addDocumentTo(ctx.state, { kind: "experiment", id: experimentId }, doc, ATTACHED_SOURCE, ctx.now);
  const stored = findExperiment(ctx.state, experimentId).documents.find((d) => d.title === doc.title && d.text === doc.text);
  return stored!.id;
}

function newestProcedure(state: SampleState, experimentId: string): WorkOrder | undefined {
  return state.orders.filter((o) => o.experiment_id === experimentId && o.kind === "procedure").at(-1);
}

/** The Coomassie demo: the attachment becomes step 4's source in a new order, WO-2. */
async function rewriteCoomassie(
  ctx: SampleContext, file: File, log: ReturnType<typeof activityLog>,
): Promise<{ ref: OutputRef; passed: boolean }> {
  const { state } = ctx;
  const docId = await attach(ctx, COOMASSIE, file);
  await log.emit({ label: "Read your attachment", outcome: "done" });

  const experiment = findExperiment(state, COOMASSIE);
  const previous = state.orders.find((o) => o.id === COOMASSIE_ORDER)!;
  const first = submissionsOf(state, previous.id)[0];
  const steps = copy((first.artifact as { steps: ProcedureStep[] }).steps);
  steps[3] = { ...steps[3], citations: [docId] };
  const documents = documentsFor(state, COOMASSIE);
  const instruments = state.lab.instruments;
  // Checked as the seed checks WO-1, so the two submissions compare like for like.
  const results = procedureResults(steps, documents, instruments, false);
  const { order, submission } = await storeOrder(ctx, {
    experimentId: COOMASSIE, kind: "procedure", objective: previous.objective, pins: currentPins(state, experiment),
    artifact: { steps }, results, views: procedureViews(steps, results, documents, instruments),
  });
  await log.emit({ label: "Rewrote procedure", outcome: "done" });
  await log.emit(checksItem(submission.results));
  return {
    ref: { kind: "procedure", work_order_id: order.id, summary: submissionSummary(1, submission.results) },
    passed: submission.passed,
  };
}

/**
 * Appends the person's message (before anything awaits, so it is never lost), then the
 * factory's scripted reply. Returns both new messages.
 */
export async function sendMessage(
  ctx: SampleContext, experimentId: string, text: string, files: File[], options: ActivityOptions = {},
): Promise<Message[]> {
  const { state } = ctx;
  findExperiment(state, experimentId);
  const body = text.trim();
  if (body === "" && files.length === 0) throw new ClientError("invalid", "Write a message or attach a file.");
  const person = appendMessage(ctx, experimentId, {
    from: "person", text: body, ...(files.length > 0 ? { attachments: files.map(attachmentTitle) } : {}),
  });

  if (files.length === 0) {
    const reply = appendMessage(ctx, experimentId, { from: "factory", text: SAMPLE_REPLY });
    return [copy(person), copy(reply)];
  }

  const inFlight = rewriting.get(state) ?? new Set<string>();
  rewriting.set(state, inFlight);
  const scripted = experimentId === COOMASSIE && !inFlight.has(COOMASSIE)
    && newestProcedure(state, COOMASSIE)?.id === COOMASSIE_ORDER;
  if (scripted) {
    inFlight.add(COOMASSIE);
    try {
      const log = activityLog(person.id, options);
      const { ref, passed } = await rewriteCoomassie(ctx, files[0], log);
      const reply = appendMessage(ctx, experimentId, {
        from: "factory",
        text: passed
          ? `I added ${attachmentTitle(files[0])} to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.`
          : `I added ${attachmentTitle(files[0])} to this experiment and rewrote the procedure. Some checks failed, so nothing is waiting for sign-off yet.`,
        activity: log.items, output_refs: [ref],
      });
      return [copy(person), copy(reply)];
    } finally {
      inFlight.delete(COOMASSIE);
    }
  }

  for (const file of files) await attach(ctx, experimentId, file);
  const reply = appendMessage(ctx, experimentId, {
    from: "factory",
    text: `I added ${listNames(files.map(attachmentTitle))} to this experiment. Tell me what to change and I’ll rebuild.`,
  });
  return [copy(person), copy(reply)];
}
