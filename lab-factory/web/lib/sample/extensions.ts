// The sample client's skills, connectors and agent setup: plain functions over
// SampleState, wired into the client by client.ts. As in records.ts, validation and
// mutation happen synchronously; a save that must hash checks again after the await.
import { canonicalDigest } from "../digest.ts";
import { ClientError } from "../types.ts";
import type {
  AgentConnection, AgentSetup, Connector, ConnectorId, DocumentTarget, NewDocument, Pin, Revision, Skill,
} from "../types.ts";
import { AGENT_SETUP } from "./agent-setup.ts";
import { addDocumentTo, copy, findExperiment, findProject, getLabOf, revisionKey, uniqueSlug } from "./records.ts";
import type { SampleContext } from "./records.ts";
import type { SampleState } from "./seed.ts";

export type SkillInput = { id?: string; title: string; description: string; body: string };

// ---------------------------------------------------------------- skills

/** The digest of a skill as stored: its content, without `enabled` and `revision` (as the seed does). */
export function skillDigest(skill: Skill): Promise<string> {
  const { enabled: _enabled, revision: _revision, ...record } = skill;
  return canonicalDigest(record);
}

export function findSkill(state: SampleState, skillId: string): Skill {
  const skill = state.skills.find((s) => s.id === skillId);
  if (!skill) throw new ClientError("not_found", `Unknown skill ${skillId}.`);
  return skill;
}

function latestRevision(state: SampleState, skillId: string): Revision {
  const revisions = state.revisions[revisionKey("skill", skillId)] ?? [];
  if (revisions.length === 0) throw new ClientError("not_found", `Skill ${skillId} has no revisions.`);
  return revisions[revisions.length - 1];
}

/** Enabled skills, in seed (list) order. Returned as copies. */
export function enabledSkills(state: SampleState): Skill[] {
  return copy(state.skills.filter((s) => s.enabled));
}

/** A pin of each enabled skill's latest revision, in seed order: what a new work order carries. */
export function enabledSkillPins(state: SampleState): Pin[] {
  return state.skills.filter((s) => s.enabled).map((s): Pin => {
    const latest = latestRevision(state, s.id);
    return { kind: "skill", id: s.id, revision: latest.number, digest: latest.digest };
  });
}

export function listSkills(ctx: SampleContext, labId: string): Skill[] {
  getLabOf(ctx.state, labId);
  return copy(ctx.state.skills);
}

export async function saveSkill(ctx: SampleContext, labId: string, input: SkillInput): Promise<Skill> {
  const { state } = ctx;
  for (;;) {
    getLabOf(state, labId);
    const title = input.title.trim();
    const description = input.description.trim();
    const body = input.body;
    if (title === "" || body.trim() === "") throw new ClientError("invalid", "A skill needs a title and instructions.");

    if (input.id === undefined) {
      const skill: Skill = {
        id: uniqueSlug(title, state.skills.map((s) => s.id), "skill"), title, description, body, enabled: true, revision: 1,
      };
      const digest = await skillDigest(skill);
      // Another save may have taken the id while hashing: start again.
      if (state.skills.some((s) => s.id === skill.id)) continue;
      state.skills.push(skill);
      state.revisions[revisionKey("skill", skill.id)] = [{ number: 1, digest, at: ctx.now().toISOString(), note: "Created" }];
      return copy(skill);
    }

    const skill = findSkill(state, input.id);
    if (skill.title === title && skill.description === description && skill.body === body) return copy(skill);
    const key = revisionKey("skill", skill.id);
    const stamp = (state.revisions[key] ?? []).length;
    const digest = await skillDigest({ ...skill, title, description, body });
    // The skill may have changed while hashing (an overlapping save): start again from the current state.
    if (stamp !== (state.revisions[key] ?? []).length || !state.skills.includes(skill)) continue;
    const revisions = (state.revisions[key] ??= []);
    revisions.push({ number: revisions.length + 1, digest, at: ctx.now().toISOString(), note: "Edited" });
    Object.assign(skill, { title, description, body, revision: revisions.length });
    return copy(skill);
  }
}

/** Switches a skill on or off. Never records a revision. */
export function setSkillEnabled(ctx: SampleContext, labId: string, skillId: string, enabled: boolean): Skill {
  getLabOf(ctx.state, labId);
  const skill = findSkill(ctx.state, skillId);
  skill.enabled = enabled === true;
  return copy(skill);
}

// ---------------------------------------------------------------- connectors

function findConnector(state: SampleState, connectorId: ConnectorId): Connector {
  const connector = state.connectors.find((c) => c.id === connectorId);
  if (!connector) throw new ClientError("not_found", `Unknown connector ${connectorId}.`);
  return connector;
}

/** A connector as callers see it: disconnected connectors show no items. */
function shown(connector: Connector): Connector {
  return copy(connector.connected ? connector : { ...connector, items: [] });
}

export function listConnectors(ctx: SampleContext, labId: string): Connector[] {
  getLabOf(ctx.state, labId);
  return ctx.state.connectors.map(shown);
}

export function connect(ctx: SampleContext, labId: string, connectorId: ConnectorId, account: string): Connector {
  getLabOf(ctx.state, labId);
  const connector = findConnector(ctx.state, connectorId);
  const name = account.trim();
  if (name === "") throw new ClientError("invalid", "Enter an account or folder name.");
  connector.connected = true;
  connector.account = name;
  return shown(connector);
}

export function disconnect(ctx: SampleContext, labId: string, connectorId: ConnectorId): Connector {
  getLabOf(ctx.state, labId);
  const connector = findConnector(ctx.state, connectorId);
  connector.connected = false;
  connector.account = null;
  return shown(connector);
}

/** Adds a connector item to a project or experiment through the same path as addDocument. */
export function importFromConnector(
  ctx: SampleContext, labId: string, connectorId: ConnectorId, itemId: string, target: DocumentTarget,
): Promise<Revision> {
  const { state } = ctx;
  getLabOf(state, labId);
  const connector = findConnector(state, connectorId);
  if (target.kind === "project") findProject(state, target.id);
  else findExperiment(state, target.id);
  if (!connector.connected) throw new ClientError("refused", `Connect ${connector.name} first.`);
  const item = connector.items.find((i) => i.id === itemId);
  if (!item) throw new ClientError("not_found", `Unknown item ${itemId} in ${connector.name}.`);
  if (item.kind === "readings") throw new ClientError("invalid", "Readings go to an experiment's Results tab.");
  const doc: NewDocument = { title: item.title, kind: item.kind === "code" ? "note" : item.kind, text: item.text };
  return addDocumentTo(state, target, doc, `${connector.name}: ${connector.account}`, ctx.now);
}

// ---------------------------------------------------------------- agents

/** One entry per worker that has claimed an order: its latest claim and its orders, newest first. */
export function listAgentConnections(ctx: SampleContext, labId: string): AgentConnection[] {
  const { state } = ctx;
  getLabOf(state, labId);
  const claims: { worker: string; order: string; at: string }[] = [];
  for (const [order, events] of Object.entries(state.history)) {
    for (const e of events) if (e.event === "claimed") claims.push({ worker: e.actor, order, at: e.at });
  }
  claims.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  const byWorker = new Map<string, AgentConnection>();
  for (const claim of claims) {
    const entry = byWorker.get(claim.worker);
    if (!entry) byWorker.set(claim.worker, { worker: claim.worker, last_seen: claim.at, work_order_ids: [claim.order] });
    else if (!entry.work_order_ids.includes(claim.order)) entry.work_order_ids.push(claim.order);
  }
  return copy([...byWorker.values()]);
}

export function getAgentSetup(ctx: SampleContext, labId: string): AgentSetup {
  getLabOf(ctx.state, labId);
  return copy(AGENT_SETUP);
}
