// The sample LabFactoryClient: an in-memory lab seeded by createSeed. All logic lives in
// records.ts (and the files Tasks 6 and 7 add); this file only wires it to the interface.
import { ClientError } from "../types.ts";
import type { LabFactoryClient } from "../types.ts";
import * as records from "./records.ts";
import type { SampleContext } from "./records.ts";
import { createSeed } from "./seed.ts";
import type { SampleState } from "./seed.ts";

export type SampleClientOptions = { delayMs?: number; stepMs?: number; now?: () => Date };

export function createSampleClient(options: SampleClientOptions = {}): LabFactoryClient & { reset(): Promise<void> } {
  const delayMs = options.delayMs ?? 0;
  const now = options.now ?? (() => new Date());
  // stepMs (between activity items) is used by the conversation engine in Task 7.
  let loading: Promise<SampleState> | null = null;
  const load = (): Promise<SampleState> => (loading ??= createSeed(now()));

  // Waits for the delay and the one shared seed, then hands out the context. Everything
  // after this await runs synchronously in the records functions.
  async function context(): Promise<SampleContext> {
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    return { state: await load(), now };
  }
  const run = async <T>(fn: (ctx: SampleContext) => T | Promise<T>): Promise<T> => fn(await context());
  // Placeholder for a method a later task wires in.
  const later = async <T>(): Promise<T> => {
    await context();
    throw new ClientError("refused", "Not available yet.");
  };

  return {
    async reset() {
      loading = createSeed(now());
      await loading;
    },
    getLab: (labId) => run((c) => records.getLab(c, labId)),
    listProjects: (labId) => run((c) => records.listProjects(c, labId)),
    getProject: (id) => run((c) => records.getProject(c, id)),
    createProject: (labId, title, goals) => run((c) => records.createProject(c, labId, title, goals)),
    createExperiment: (projectId, description, instrumentIds) =>
      run((c) => records.createExperiment(c, projectId, description, instrumentIds)),
    getWorkspace: (id) => run((c) => records.getWorkspace(c, id)),
    getSubmissionView: (id, n) => run((c) => records.getSubmissionView(c, id, n)),
    approve: (id, n, person) => run((c) => records.approve(c, id, n, person)),
    reject: (id, n, person, reason) => run((c) => records.reject(c, id, n, person, reason)),
    needsAttention: (labId, role) => run((c) => records.needsAttention(c, labId, role)),
    addDocument: (target, doc) => run((c) => records.addDocument(c, target, doc)),
    listRevisions: (kind, id) => run((c) => records.listRevisions(c, kind, id)),
    getSettings: (labId) => run((c) => records.getSettings(c, labId)),
    updateSettings: (labId, settings) => run((c) => records.updateSettings(c, labId, settings)),
    search: (labId, query) => run((c) => records.search(c, labId, query)),

    // Task 7 (conversation engine) replaces these two.
    sendMessage: () => later(),
    confirmPlan: () => later(),
    // Task 6 (skills, connectors, agent setup) replaces these.
    listSkills: () => later(),
    saveSkill: () => later(),
    setSkillEnabled: () => later(),
    listConnectors: () => later(),
    connect: () => later(),
    disconnect: () => later(),
    importFromConnector: () => later(),
    listAgentConnections: () => later(),
    getAgentSetup: () => later(),
  };
}
