// The live client: the LabFactoryClient interface over the HTTP contract in API.md.
// Runs under Node type stripping, so it keeps to erasable TypeScript and touches no
// browser-only globals at module load.

import { ClientError } from "../types.ts";
import type {
  ActivityItem, AgentConnection, AgentSetup, AttentionItem, ClientErrorCode, Connector, ConnectorId,
  DocumentTarget, Experiment, LabFactoryClient, Lab, LabSettings, Message, NewDocument, OnActivity, OutputKind,
  Pin, Project, Revision, Role, RunStepView, SearchHit, Skill, StepView, Submission, WorkOrder, Workspace,
} from "../types.ts";

const STATUS_CODES: Record<number, ClientErrorCode> = { 404: "not_found", 409: "refused", 422: "invalid" };
const ERROR_CODES: readonly ClientErrorCode[] = ["not_found", "invalid", "refused"];

const REVISION_PATHS: Record<Pin["kind"], string> = {
  lab: "labs", project: "projects", experiment: "experiments", skill: "skills",
};
const DOCUMENT_PATHS: Record<DocumentTarget["kind"], string> = { project: "projects", experiment: "experiments" };

type Query = Record<string, string>;
type Body = { json: unknown } | { form: FormData };

function statusError(status: number): ClientError {
  return new ClientError("refused", `The Lab Factory service returned ${status}.`);
}

function unreachable(): ClientError {
  return new ClientError("refused", "The Lab Factory service couldn't be reached.");
}

function path(...segments: (string | number)[]): string {
  return segments.map((s) => "/" + encodeURIComponent(String(s))).join("");
}

async function errorFrom(response: Response): Promise<ClientError> {
  const code = STATUS_CODES[response.status];
  if (code !== undefined) {
    try {
      const body: unknown = await response.json();
      if (body !== null && typeof body === "object" && "message" in body && typeof body.message === "string") {
        return new ClientError(code, body.message);
      }
    } catch {
      // Not JSON: fall through to the generic status message.
    }
  }
  return statusError(response.status);
}

function isErrorCode(value: unknown): value is ClientErrorCode {
  return typeof value === "string" && (ERROR_CODES as readonly string[]).includes(value);
}

async function readStream(response: Response, onActivity?: OnActivity): Promise<Message[]> {
  if (response.body === null) throw statusError(response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let messages: Message[] | null = null;

  const handle = (line: string) => {
    if (line.trim() === "") return;
    let event: { type?: unknown; item?: unknown; messages?: unknown; code?: unknown; message?: unknown };
    try {
      event = JSON.parse(line);
    } catch {
      throw statusError(response.status);
    }
    if (event === null || typeof event !== "object") throw statusError(response.status);
    if (event.type === "activity") {
      onActivity?.(event.item as ActivityItem);
    } else if (event.type === "messages" && Array.isArray(event.messages)) {
      messages = event.messages as Message[];
    } else if (event.type === "error") {
      const code = isErrorCode(event.code) ? event.code : "refused";
      const text = typeof event.message === "string" ? event.message : `The Lab Factory service returned ${response.status}.`;
      throw new ClientError(code, text);
    }
  };

  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch {
        throw unreachable();
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        handle(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
    }
    buffer += decoder.decode();
    handle(buffer);
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }

  if (messages === null) {
    throw new ClientError("refused", "The Lab Factory service ended the reply without any messages.");
  }
  return messages;
}

export function createLiveClient(baseUrl: string, options?: { fetch?: typeof fetch }): LabFactoryClient {
  const base = baseUrl.replace(/\/+$/, "");

  async function send(method: string, route: string, init: { query?: Query; body?: Body; stream?: boolean } = {}) {
    const fetchImpl = options?.fetch ?? globalThis.fetch;
    let url = base + route;
    if (init.query !== undefined) {
      url += "?" + Object.entries(init.query)
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`).join("&");
    }
    const headers: Record<string, string> = { accept: init.stream ? "application/x-ndjson" : "application/json" };
    let body: BodyInit | undefined;
    if (init.body !== undefined && "json" in init.body) {
      headers["content-type"] = "application/json";
      body = JSON.stringify(init.body.json);
    } else if (init.body !== undefined) {
      body = init.body.form;
    }
    let response: Response;
    try {
      response = await fetchImpl(url, { method, headers, body, credentials: "include" });
    } catch {
      throw unreachable();
    }
    if (!response.ok) throw await errorFrom(response);
    return response;
  }

  async function call<T>(method: string, route: string, init: { query?: Query; json?: unknown } = {}): Promise<T> {
    const body = init.json === undefined ? undefined : { json: init.json };
    const response = await send(method, route, { query: init.query, body });
    try {
      return (await response.json()) as T;
    } catch {
      throw statusError(response.status);
    }
  }

  async function stream(route: string, body: Body, onActivity?: OnActivity): Promise<Message[]> {
    return readStream(await send("POST", route, { body, stream: true }), onActivity);
  }

  const lab = (labId: string, ...rest: string[]) => path("labs", labId, ...rest);

  return {
    getLab: (labId) => call<Lab>("GET", lab(labId)),
    listProjects: (labId) =>
      call<(Project & { experiments: Pick<Experiment, "id" | "title">[] })[]>("GET", lab(labId, "projects")),
    getProject: (projectId) => call<Project & { experiments: Experiment[] }>("GET", path("projects", projectId)),
    createProject: (labId, title, goals) =>
      call<Project>("POST", lab(labId, "projects"), { json: { title, goals } }),
    createExperiment: (projectId, description, instrumentIds) =>
      call<Experiment>("POST", path("projects", projectId, "experiments"),
        { json: { description, instrument_ids: instrumentIds } }),
    getWorkspace: (experimentId) => call<Workspace>("GET", path("experiments", experimentId, "workspace")),
    getSubmissionView: (workOrderId, number) =>
      call<{ submission: Submission; steps: (StepView | RunStepView)[] }>(
        "GET", path("work-orders", workOrderId, "submissions", number)),
    sendMessage: (experimentId, text, attachments, onActivity) => {
      const form = new FormData();
      form.append("text", text);
      for (const file of attachments) form.append("files", file, file.name);
      return stream(path("experiments", experimentId, "messages"), { form }, onActivity);
    },
    confirmPlan: (experimentId, messageId, outputs: OutputKind[], onActivity) =>
      stream(path("experiments", experimentId, "plan"), { json: { message_id: messageId, outputs } }, onActivity),
    approve: (workOrderId, submission, person) =>
      call<WorkOrder>("POST", path("work-orders", workOrderId, "approve"), { json: { submission, person } }),
    reject: (workOrderId, submission, person, reason) =>
      call<WorkOrder>("POST", path("work-orders", workOrderId, "reject"), { json: { submission, person, reason } }),
    needsAttention: (labId, role: Role) =>
      call<AttentionItem[]>("GET", lab(labId, "attention"), { query: { role } }),
    addDocument: (target, doc: NewDocument) =>
      call<Revision>("POST", path(DOCUMENT_PATHS[target.kind], target.id, "documents"),
        { json: { title: doc.title, kind: doc.kind, text: doc.text } }),
    listRevisions: (kind, id) => call<Revision[]>("GET", path(REVISION_PATHS[kind], id, "revisions")),
    getSettings: (labId) => call<LabSettings>("GET", lab(labId, "settings")),
    updateSettings: (labId, settings) => call<LabSettings>("PUT", lab(labId, "settings"), { json: settings }),
    search: (labId, query) => call<SearchHit[]>("GET", lab(labId, "search"), { query: { q: query } }),
    listSkills: (labId) => call<Skill[]>("GET", lab(labId, "skills")),
    saveSkill: (labId, skill) => {
      const json = { title: skill.title, description: skill.description, body: skill.body };
      return skill.id === undefined
        ? call<Skill>("POST", lab(labId, "skills"), { json })
        : call<Skill>("PUT", lab(labId, "skills", skill.id), { json });
    },
    setSkillEnabled: (labId, skillId, enabled) =>
      call<Skill>("POST", lab(labId, "skills", skillId, "enabled"), { json: { enabled } }),
    listConnectors: (labId) => call<Connector[]>("GET", lab(labId, "connectors")),
    connect: (labId, connectorId: ConnectorId, account) =>
      call<Connector>("POST", lab(labId, "connectors", connectorId, "connect"), { json: { account } }),
    disconnect: (labId, connectorId) => call<Connector>("POST", lab(labId, "connectors", connectorId, "disconnect")),
    importFromConnector: (labId, connectorId, itemId, target: DocumentTarget) =>
      call<Revision>("POST", lab(labId, "connectors", connectorId, "items", itemId, "import"),
        { json: { target: { kind: target.kind, id: target.id } } }),
    listAgentConnections: (labId) => call<AgentConnection[]>("GET", lab(labId, "agents")),
    getAgentSetup: (labId) => call<AgentSetup>("GET", lab(labId, "agent-setup")),
  };
}
