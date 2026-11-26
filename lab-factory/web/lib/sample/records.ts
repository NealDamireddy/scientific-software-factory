// The sample client's logic: plain functions over SampleState. client.ts only wires
// them to the LabFactoryClient interface. Every function that validates and then
// mutates does both in one synchronous block, so overlapping calls cannot both pass.
// Functions that must hash (a new revision digest) check again after the await and
// retry if the record changed meanwhile.
import { canonicalDigest } from "../digest.ts";
import { ClientError } from "../types.ts";
import type {
  AttentionItem, Document, DocumentTarget, Experiment, HistoryEvent, Instrument, Lab, LabSettings,
  NewDocument, Message, OrderView, Pin, Project, Revision, Role, RunStepView, SearchHit,
  StepView, Submission, WorkOrder, Workspace,
} from "../types.ts";
import type { SampleState } from "./seed.ts";

/** What every record function needs: the store and a clock. */
export type SampleContext = { state: SampleState; now: () => Date };

export const ADDED_SOURCE = "Added in Lab Factory";
const DOCUMENT_KINDS = ["sop", "manual", "standard", "paper", "note"];
const SEARCH_LIMIT = 20;

// ---------------------------------------------------------------- helpers

/** A deep copy, so callers can never mutate the store through a result. */
export function copy<T>(value: T): T {
  return structuredClone(value);
}

/** Lowercase letters and digits joined by single hyphens; accented letters fold to ASCII. */
export function slugify(text: string, fallback = "item"): string {
  const slug = text.normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug === "" ? fallback : slug;
}

/** slugify(text), then `-2`, `-3`, ... until the id is not in `taken`. */
export function uniqueSlug(text: string, taken: Iterable<string>, fallback = "item"): string {
  const used = new Set(taken);
  const base = slugify(text, fallback);
  if (!used.has(base)) return base;
  for (let n = 2; ; n += 1) {
    if (!used.has(`${base}-${n}`)) return `${base}-${n}`;
  }
}

export function revisionKey(kind: Pin["kind"], id: string): string {
  return `${kind}:${id}`;
}

export function getLabOf(state: SampleState, labId: string): Lab {
  if (state.lab.id !== labId) throw new ClientError("not_found", `Unknown lab ${labId}.`);
  return state.lab;
}

export function findProject(state: SampleState, projectId: string): Project {
  const project = state.projects.find((p) => p.id === projectId);
  if (!project) throw new ClientError("not_found", `Unknown project ${projectId}.`);
  return project;
}

export function findExperiment(state: SampleState, experimentId: string): Experiment {
  const experiment = state.experiments.find((e) => e.id === experimentId);
  if (!experiment) throw new ClientError("not_found", `Unknown experiment ${experimentId}.`);
  return experiment;
}

export function findOrder(state: SampleState, workOrderId: string): WorkOrder {
  const order = state.orders.find((o) => o.id === workOrderId);
  if (!order) throw new ClientError("not_found", `Unknown work order ${workOrderId}.`);
  return order;
}

export function submissionsOf(state: SampleState, workOrderId: string): Submission[] {
  return state.submissions.filter((s) => s.work_order_id === workOrderId).sort((a, b) => a.number - b.number);
}

/** The lab, project and experiment documents an experiment's orders can cite. */
export function documentsFor(state: SampleState, experimentId: string): Document[] {
  const experiment = findExperiment(state, experimentId);
  const project = findProject(state, experiment.project_id);
  return [...state.lab.documents, ...project.documents, ...experiment.documents];
}

/** Every document id that a new document in this project (or one of its experiments) must not reuse. */
export function takenDocumentIds(state: SampleState, projectId: string): string[] {
  const ids = state.lab.documents.map((d) => d.id);
  const project = state.projects.find((p) => p.id === projectId);
  if (project) ids.push(...project.documents.map((d) => d.id));
  for (const e of state.experiments) if (e.project_id === projectId) ids.push(...e.documents.map((d) => d.id));
  return ids;
}

/** The digest of a record as the backend would see it: experiments carry no project_id. */
export function recordDigest(kind: "project" | "experiment", record: Project | Experiment): Promise<string> {
  if (kind === "experiment") {
    const { project_id: _project, ...rest } = record as Experiment;
    return canonicalDigest(rest);
  }
  return canonicalDigest(record);
}

export function nextMessageId(state: SampleState, experimentId: string): string {
  const existing = new Set((state.messages[experimentId] ?? []).map((m) => m.id));
  for (let n = existing.size + 1; ; n += 1) {
    if (!existing.has(`${experimentId}-m${n}`)) return `${experimentId}-m${n}`;
  }
}

export function appendMessage(ctx: SampleContext, experimentId: string, message: Omit<Message, "id" | "at">): Message {
  const full: Message = { id: nextMessageId(ctx.state, experimentId), at: ctx.now().toISOString(), ...message };
  (ctx.state.messages[experimentId] ??= []).push(full);
  return full;
}

function ownerOf(state: SampleState, target: DocumentTarget): Project | Experiment {
  return target.kind === "project" ? findProject(state, target.id) : findExperiment(state, target.id);
}

function projectIdOf(owner: Project | Experiment, target: DocumentTarget): string {
  return target.kind === "project" ? owner.id : (owner as Experiment).project_id;
}

// ---------------------------------------------------------------- documents and revisions

/**
 * The one path that adds a document to a project or experiment and records a revision.
 * `addDocument` uses it with source "Added in Lab Factory"; connector imports and
 * attachments use it with their own source. Identical title and text already on the
 * target returns the latest revision unchanged.
 */
export async function addDocumentTo(
  state: SampleState, target: DocumentTarget, doc: NewDocument, source: string, now: () => Date,
): Promise<Revision> {
  for (;;) {
    const owner = ownerOf(state, target);
    const title = doc.title.trim();
    if (title === "" || doc.text.trim() === "") throw new ClientError("invalid", "A document needs a title and text.");
    if (!DOCUMENT_KINDS.includes(doc.kind)) throw new ClientError("invalid", `Unknown document kind ${doc.kind}.`);
    const key = revisionKey(target.kind, owner.id);
    const revisions = state.revisions[key] ?? [];
    const same = owner.documents.find((d) => d.title === title && d.text === doc.text);
    if (same && revisions.length > 0) return copy(revisions[revisions.length - 1]);

    const stamp = `${owner.documents.length}:${revisions.length}`;
    const id = uniqueSlug(title, takenDocumentIds(state, projectIdOf(owner, target)), "document");
    const added: Document = { id, kind: doc.kind, title, source, text: doc.text };
    const digest = await recordDigest(target.kind, { ...owner, documents: [...owner.documents, added] });
    // The record may have changed while hashing, or an overlapping add elsewhere in the
    // project may have taken the id: start again from the current state.
    if (stamp !== `${owner.documents.length}:${(state.revisions[key] ?? []).length}`) continue;
    if (takenDocumentIds(state, projectIdOf(owner, target)).includes(id)) continue;

    owner.documents.push(added);
    const revision: Revision = { number: revisions.length + 1, digest, at: now().toISOString(), note: `Added ${title}` };
    (state.revisions[key] ??= []).push(revision);
    return copy(revision);
  }
}

export function addDocument(ctx: SampleContext, target: DocumentTarget, doc: NewDocument): Promise<Revision> {
  return addDocumentTo(ctx.state, target, doc, ADDED_SOURCE, ctx.now);
}

export function listRevisions(ctx: SampleContext, kind: Pin["kind"], id: string): Revision[] {
  const revisions = ctx.state.revisions[revisionKey(kind, id)];
  if (!revisions) throw new ClientError("not_found", `Unknown ${kind} ${id}.`);
  return copy(revisions);
}

// ---------------------------------------------------------------- lab, projects, experiments

export function getLab(ctx: SampleContext, labId: string): Lab {
  return copy(getLabOf(ctx.state, labId));
}

export function listProjects(ctx: SampleContext, labId: string): (Project & { experiments: Pick<Experiment, "id" | "title">[] })[] {
  getLabOf(ctx.state, labId);
  return ctx.state.projects.map((p) => copy({
    ...p,
    experiments: ctx.state.experiments.filter((e) => e.project_id === p.id).map((e) => ({ id: e.id, title: e.title })),
  }));
}

export function getProject(ctx: SampleContext, projectId: string): Project & { experiments: Experiment[] } {
  const project = findProject(ctx.state, projectId);
  return copy({ ...project, experiments: ctx.state.experiments.filter((e) => e.project_id === projectId) });
}

export async function createProject(ctx: SampleContext, labId: string, title: string, goals: string): Promise<Project> {
  const { state } = ctx;
  for (;;) {
    getLabOf(state, labId);
    if (title.trim() === "" || goals.trim() === "") throw new ClientError("invalid", "A project needs a title and goals.");
    const project: Project = {
      id: uniqueSlug(title, state.projects.map((p) => p.id), "project"),
      lab_id: labId, title: title.trim(), goals: goals.trim(), documents: [],
    };
    const digest = await recordDigest("project", project);
    if (state.projects.some((p) => p.id === project.id)) continue;
    state.projects.push(project);
    state.revisions[revisionKey("project", project.id)] = [{ number: 1, digest, at: ctx.now().toISOString(), note: "Created" }];
    return copy(project);
  }
}

/** The description cut to 60 characters at a word boundary. */
export function experimentTitle(description: string): string {
  const text = description.trim().replace(/\s+/g, " ");
  if (text.length <= 60) return text;
  if (text[60] === " ") return text.slice(0, 60);
  const cut = text.slice(0, 60);
  const space = cut.lastIndexOf(" ");
  return (space > 0 ? cut.slice(0, space) : cut).trimEnd();
}

export async function createExperiment(
  ctx: SampleContext, projectId: string, description: string, instrumentIds: string[],
): Promise<Experiment> {
  const { state } = ctx;
  for (;;) {
    const project = findProject(state, projectId);
    if (description.trim() === "") throw new ClientError("invalid", "Describe what you want to do.");
    const known = new Set(state.lab.instruments.map((i: Instrument) => i.id));
    for (const id of instrumentIds) {
      if (!known.has(id)) throw new ClientError("invalid", `Unknown instrument ${id}.`);
    }
    const title = experimentTitle(description);
    const experiment: Experiment = {
      id: uniqueSlug(title, state.experiments.map((e) => e.id), "experiment"),
      lab_id: project.lab_id, project_id: project.id, title, goal: description.trim(),
      instrument_ids: [...new Set(instrumentIds)], documents: [],
    };
    const digest = await recordDigest("experiment", experiment);
    if (state.experiments.some((e) => e.id === experiment.id)) continue;
    state.experiments.push(experiment);
    state.revisions[revisionKey("experiment", experiment.id)] = [{ number: 1, digest, at: ctx.now().toISOString(), note: "Created" }];
    state.messages[experiment.id] = [];
    return copy(experiment);
  }
}

// ---------------------------------------------------------------- workspace and views

function orderView<S extends StepView | RunStepView>(state: SampleState, order: WorkOrder): OrderView<S> {
  const submissions = submissionsOf(state, order.id);
  const shown = submissions.length > 0 ? submissions[submissions.length - 1].number : 0;
  return copy({
    order, submissions, shown,
    steps: (state.views[`${order.id}#${shown}`] ?? []) as S[],
    history: state.history[order.id] ?? [],
  });
}

export function getWorkspace(ctx: SampleContext, experimentId: string): Workspace {
  const { state } = ctx;
  const experiment = findExperiment(state, experimentId);
  const orders = state.orders.filter((o) => o.experiment_id === experimentId);
  const newest = (kind: WorkOrder["kind"]): WorkOrder | undefined => orders.filter((o) => o.kind === kind).at(-1);
  const procedure = newest("procedure");
  const runPlan = newest("run_plan");
  const workspace: Workspace = {
    experiment: copy(experiment),
    project: copy(findProject(state, experiment.project_id)),
    messages: copy(state.messages[experimentId] ?? []),
  };
  if (procedure) workspace.procedure = orderView<StepView>(state, procedure);
  if (runPlan) workspace.run_plan = orderView<RunStepView>(state, runPlan);
  if (state.apps[experimentId]) workspace.analysis_app = copy(state.apps[experimentId]);
  if (state.simulations[experimentId]) workspace.simulation = copy(state.simulations[experimentId]);
  return workspace;
}

export function getSubmissionView(
  ctx: SampleContext, workOrderId: string, number: number,
): { submission: Submission; steps: (StepView | RunStepView)[] } {
  const submission = ctx.state.submissions.find((s) => s.work_order_id === workOrderId && s.number === number);
  if (!submission) throw new ClientError("not_found", `Unknown submission ${number} of ${workOrderId}.`);
  return copy({ submission, steps: ctx.state.views[`${workOrderId}#${number}`] ?? [] });
}

// ---------------------------------------------------------------- settings

export function getSettings(ctx: SampleContext, labId: string): LabSettings {
  getLabOf(ctx.state, labId);
  return copy(ctx.state.settings);
}

/** A name as the sign-off rule compares it: trimmed, inner whitespace runs collapsed to one space. */
function tidyName(name: string): string {
  return name.trim().replace(/\s+/g, " ");
}

export function updateSettings(ctx: SampleContext, labId: string, settings: LabSettings): LabSettings {
  getLabOf(ctx.state, labId);
  const rule = settings.sign_off;
  if (rule.mode === "listed") {
    // De-duplicated case-insensitively, keeping the first spelling.
    const names: string[] = [];
    for (const raw of rule.names) {
      const name = tidyName(raw);
      if (name !== "" && !names.some((n) => n.toLowerCase() === name.toLowerCase())) names.push(name);
    }
    if (names.length === 0) throw new ClientError("invalid", "Name at least one person who can sign off.");
    ctx.state.settings = { sign_off: { mode: "listed", names } };
  } else {
    ctx.state.settings = { sign_off: { mode: "anyone" } };
  }
  return copy(ctx.state.settings);
}

// ---------------------------------------------------------------- search

function matches(query: string, ...fields: string[]): boolean {
  return fields.some((f) => f.toLowerCase().includes(query));
}

/** Projects, experiments, documents, instruments, skills, then connectors. */
export function searchHits(state: SampleState, query: string): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (q === "") return [];
  const hits: SearchHit[] = [];
  for (const p of state.projects) {
    if (matches(q, p.title, p.id)) hits.push({ kind: "project", id: p.id, title: p.title, href: `#/projects/${p.id}` });
  }
  const experimentHref = (e: Experiment): string => `#/projects/${e.project_id}/experiments/${e.id}`;
  for (const e of state.experiments) {
    if (matches(q, e.title, e.id)) hits.push({ kind: "experiment", id: e.id, title: e.title, href: experimentHref(e) });
  }
  const docHit = (d: Document, page: string): void => {
    if (matches(q, d.title, d.id)) hits.push({ kind: "document", id: d.id, title: d.title, href: `${page}?doc=${d.id}` });
  };
  for (const d of state.lab.documents) docHit(d, "#/lab");
  for (const p of state.projects) for (const d of p.documents) docHit(d, `#/projects/${p.id}`);
  for (const e of state.experiments) for (const d of e.documents) docHit(d, experimentHref(e));
  for (const i of state.lab.instruments) {
    if (matches(q, i.name, i.id)) hits.push({ kind: "instrument", id: i.id, title: i.name, href: "#/lab" });
  }
  for (const s of state.skills) {
    if (matches(q, s.title, s.id)) hits.push({ kind: "skill", id: s.id, title: s.title, href: `#/skills?skill=${s.id}` });
  }
  for (const c of state.connectors) {
    if (matches(q, c.name, c.id)) hits.push({ kind: "connector", id: c.id, title: c.name, href: "#/connectors" });
  }
  return hits;
}

export function search(ctx: SampleContext, labId: string, query: string): SearchHit[] {
  getLabOf(ctx.state, labId);
  return searchHits(ctx.state, query).slice(0, SEARCH_LIMIT);
}

// ---------------------------------------------------------------- sign-off

function checkSignOff(state: SampleState, order: WorkOrder, submission: number, name: string): void {
  const latest = submissionsOf(state, order.id).at(-1);
  if (latest && submission !== latest.number) {
    throw new ClientError("refused", `Submission ${submission} is not the latest. Review submission ${latest.number}.`);
  }
  if (!latest || order.status !== "in_review") {
    throw new ClientError("refused", "This submission isn't waiting for sign-off.");
  }
  const rule = state.settings.sign_off;
  if (rule.mode === "listed" && !rule.names.some((n) => tidyName(n).toLowerCase() === tidyName(name).toLowerCase())) {
    throw new ClientError("refused", `${name} isn't on this lab's sign-off list.`);
  }
}

function event(ctx: SampleContext, order: WorkOrder, kind: HistoryEvent["event"], actor: string, submission: number, note: string): void {
  (ctx.state.history[order.id] ??= []).push({ event: kind, actor, submission, note, at: ctx.now().toISOString() });
}

/** Synchronous on purpose: validation and mutation happen in one block, so a second call sees the first. */
export function approve(ctx: SampleContext, workOrderId: string, submission: number, person: string): WorkOrder {
  const order = findOrder(ctx.state, workOrderId);
  const name = person.trim();
  if (name === "") throw new ClientError("invalid", "Enter your name to approve.");
  checkSignOff(ctx.state, order, submission, name);
  const stored = submissionsOf(ctx.state, order.id).find((s) => s.number === submission)!;
  order.status = "released";
  order.released_submission = submission;
  event(ctx, order, "approved", name, submission, stored.artifact_digest);
  return copy(order);
}

export function reject(ctx: SampleContext, workOrderId: string, submission: number, person: string, reason: string): WorkOrder {
  const order = findOrder(ctx.state, workOrderId);
  const name = person.trim();
  const why = reason.trim();
  if (name === "") throw new ClientError("invalid", "Enter your name to reject.");
  if (why === "") throw new ClientError("invalid", "Give a reason for rejecting.");
  checkSignOff(ctx.state, order, submission, name);
  order.status = "open";
  event(ctx, order, "rejected", name, submission, why);
  appendMessage(ctx, order.experiment_id, { from: "factory", text: `Thanks. I’ll revise this to address: ${why}` });
  return copy(order);
}

export function needsAttention(ctx: SampleContext, labId: string, role: Role): AttentionItem[] {
  const { state } = ctx;
  getLabOf(state, labId);
  const items: AttentionItem[] = [];
  for (const order of state.orders) {
    const lastEvent = (state.history[order.id] ?? []).at(-1);
    let kind: AttentionItem["kind"] | null = null;
    if (role === "approver") {
      if (order.status === "in_review") kind = "sign_off";
    } else if (order.status === "released") kind = "signed_off";
    else if (order.status === "open" && lastEvent?.event === "rejected") kind = "rejected";
    if (!kind) continue;
    const experiment = findExperiment(state, order.experiment_id);
    items.push({ kind, work_order_id: order.id, experiment_id: experiment.id, project_id: experiment.project_id, title: experiment.title });
  }
  return items;
}
