import assert from "node:assert/strict";
import { test } from "node:test";

import { ClientError } from "../types.ts";
import type { ActivityItem, LabFactoryClient, Message } from "../types.ts";
import { createLiveClient } from "./client.ts";

const BASE = "https://api.example.org/v1";

type Call = { url: string; init: RequestInit };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function ndjson(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "application/x-ndjson" } });
}

function stub(respond: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    return respond(call);
  }) as typeof globalThis.fetch;
  return { calls, fetch };
}

function header(init: RequestInit, name: string): string | null {
  return new Headers(init.headers).get(name);
}

const ACTIVITY_1: ActivityItem = { id: "a1", label: "Read lab context (revision 1)", outcome: "done" };
const ACTIVITY_2: ActivityItem = { id: "a2", label: "Wrote procedure", outcome: "done" };
const MESSAGE: Message = { id: "m9", from: "factory", text: "Built.", at: "2026-11-26T10:00:00Z" };

test("getLab calls GET {base}/labs/{lab} with credentials", async () => {
  const lab = { id: "emory-biophys", name: "Emory Biophysics", instruments: [], documents: [] };
  const { calls, fetch } = stub(() => json(200, lab));
  const client = createLiveClient(BASE, { fetch });
  assert.deepEqual(await client.getLab("emory-biophys"), lab);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${BASE}/labs/emory-biophys`);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(calls[0].init.body, undefined);
});

test("a trailing slash on the base URL is trimmed", async () => {
  const { calls, fetch } = stub(() => json(200, []));
  await createLiveClient(`${BASE}/`, { fetch }).listProjects("emory-biophys");
  assert.equal(calls[0].url, `${BASE}/labs/emory-biophys/projects`);
});

test("a 409 throws refused with the server's message", async () => {
  const message = "Submission 1 is not the latest. Review submission 2.";
  const { fetch } = stub(() => json(409, { code: "refused", message }));
  const client = createLiveClient(BASE, { fetch });
  await assert.rejects(client.approve("WO-B12", 1, "Dr Rivera"), (error: unknown) => {
    assert.ok(error instanceof ClientError);
    assert.equal(error.code, "refused");
    assert.equal(error.message, message);
    return true;
  });
});

test("404 maps to not_found and 422 to invalid, keeping the message", async () => {
  for (const [status, code, message] of [
    [404, "not_found", "unknown experiment nope"],
    [422, "invalid", "A reason is required to reject."],
  ] as const) {
    const { fetch } = stub(() => json(status, { code, message }));
    await assert.rejects(createLiveClient(BASE, { fetch }).getWorkspace("nope"), (error: unknown) => {
      assert.ok(error instanceof ClientError);
      assert.equal(error.code, code);
      assert.equal(error.message, message);
      return true;
    });
  }
});

test("other statuses and non-JSON error bodies become a refused status message", async () => {
  const responses = [
    json(500, { code: "refused", message: "internal detail" }),
    new Response("<html>Bad gateway</html>", { status: 502, headers: { "content-type": "text/html" } }),
    new Response("not json", { status: 409 }),
    json(404, { nothing: "useful" }),
  ];
  const expected = [500, 502, 409, 404];
  for (const [i, response] of responses.entries()) {
    const { fetch } = stub(() => response);
    await assert.rejects(createLiveClient(BASE, { fetch }).getLab("emory-biophys"), (error: unknown) => {
      assert.ok(error instanceof ClientError);
      assert.equal(error.code, "refused");
      assert.equal(error.message, `The Lab Factory service returned ${expected[i]}.`);
      return true;
    });
  }
});

test("a network failure becomes a refused ClientError", async () => {
  const fetch = (async () => { throw new TypeError("fetch failed"); }) as typeof globalThis.fetch;
  await assert.rejects(createLiveClient(BASE, { fetch }).getLab("emory-biophys"), (error: unknown) => {
    assert.ok(error instanceof ClientError);
    assert.equal(error.code, "refused");
    assert.equal(error.message, "The Lab Factory service couldn't be reached.");
    return true;
  });
});

test("an NDJSON body split mid-line emits activity in order and resolves to the messages", async () => {
  const lines = [
    JSON.stringify({ type: "activity", item: ACTIVITY_1 }),
    "",
    JSON.stringify({ type: "activity", item: ACTIVITY_2 }),
    JSON.stringify({ type: "messages", messages: [MESSAGE] }),
  ].join("\n") + "\n";
  const cut1 = 17;
  const cut2 = lines.indexOf("Wrote") + 2;
  const { calls, fetch } = stub(() => ndjson([lines.slice(0, cut1), lines.slice(cut1, cut2), lines.slice(cut2)]));
  const seen: ActivityItem[] = [];
  const result = await createLiveClient(BASE, { fetch })
    .confirmPlan("exp-1", "m2", ["procedure"], (item) => seen.push(item));
  assert.deepEqual(seen, [ACTIVITY_1, ACTIVITY_2]);
  assert.deepEqual(result, [MESSAGE]);
  assert.equal(calls[0].url, `${BASE}/experiments/exp-1/plan`);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(header(calls[0].init, "content-type"), "application/json");
  assert.equal(header(calls[0].init, "accept"), "application/x-ndjson");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { message_id: "m2", outputs: ["procedure"] });
});

test("multi-byte characters split across chunks decode correctly", async () => {
  const text = "I’ll revise this.";
  const line = JSON.stringify({ type: "messages", messages: [{ ...MESSAGE, text }] }) + "\n";
  const bytes = new TextEncoder().encode(line);
  const cut = bytes.indexOf(0xe2) + 1;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, cut));
      controller.enqueue(bytes.slice(cut));
      controller.close();
    },
  });
  const { fetch } = stub(() => new Response(body, { status: 200 }));
  const [message] = await createLiveClient(BASE, { fetch }).confirmPlan("exp-1", "m2", ["procedure"]);
  assert.equal(message.text, text);
});

test("a final messages line without a trailing newline still resolves", async () => {
  const { fetch } = stub(() => ndjson([JSON.stringify({ type: "messages", messages: [MESSAGE] })]));
  assert.deepEqual(await createLiveClient(BASE, { fetch }).confirmPlan("exp-1", "m2", ["procedure"]), [MESSAGE]);
});

test("a stream that ends without a messages line is refused", async () => {
  const { fetch } = stub(() => ndjson([JSON.stringify({ type: "activity", item: ACTIVITY_1 }) + "\n"]));
  const seen: ActivityItem[] = [];
  await assert.rejects(
    createLiveClient(BASE, { fetch }).confirmPlan("exp-1", "m2", ["procedure"], (item) => seen.push(item)),
    (error: unknown) => error instanceof ClientError && error.code === "refused",
  );
  assert.deepEqual(seen, [ACTIVITY_1]);
});

test("an error line in the stream throws its code and message", async () => {
  const { fetch } = stub(() => ndjson([
    JSON.stringify({ type: "activity", item: ACTIVITY_1 }) + "\n",
    JSON.stringify({ type: "error", code: "refused", message: "The build stopped: a check crashed." }) + "\n",
  ]));
  await assert.rejects(createLiveClient(BASE, { fetch }).confirmPlan("exp-1", "m2", ["procedure"]), (error: unknown) => {
    assert.ok(error instanceof ClientError);
    assert.equal(error.code, "refused");
    assert.equal(error.message, "The build stopped: a check crashed.");
    return true;
  });
});

test("a streaming endpoint's error status uses the JSON error envelope", async () => {
  const { fetch } = stub(() => json(409, { code: "refused", message: "This plan was already confirmed." }));
  await assert.rejects(createLiveClient(BASE, { fetch }).confirmPlan("exp-1", "m2", ["procedure"]), (error: unknown) =>
    error instanceof ClientError && error.code === "refused" && error.message === "This plan was already confirmed.");
});

test("sendMessage sends multipart with text and the files, and streams the reply", async () => {
  const { calls, fetch } = stub(() => ndjson([
    JSON.stringify({ type: "activity", item: ACTIVITY_1 }) + "\n",
    JSON.stringify({ type: "messages", messages: [MESSAGE] }) + "\n",
  ]));
  const files = [
    new File(["paper one"], "dithionite.txt", { type: "text/plain" }),
    new File(["# notes"], "notes.md", { type: "text/markdown" }),
  ];
  const seen: ActivityItem[] = [];
  const result = await createLiveClient(BASE, { fetch })
    .sendMessage("coomassie reduction", "Use this paper", files, (item) => seen.push(item));
  assert.deepEqual(result, [MESSAGE]);
  assert.deepEqual(seen, [ACTIVITY_1]);
  const { url, init } = calls[0];
  assert.equal(url, `${BASE}/experiments/coomassie%20reduction/messages`);
  assert.equal(init.method, "POST");
  assert.equal(init.credentials, "include");
  assert.equal(header(init, "content-type"), null, "the runtime sets the multipart boundary");
  assert.ok(init.body instanceof FormData);
  assert.equal(init.body.get("text"), "Use this paper");
  const sent = init.body.getAll("files") as File[];
  assert.deepEqual(sent.map((f) => f.name), ["dithionite.txt", "notes.md"]);
  assert.equal(await sent[0].text(), "paper one");
});

test("sendMessage with no files sends only the text field", async () => {
  const { calls, fetch } = stub(() => ndjson([JSON.stringify({ type: "messages", messages: [MESSAGE] }) + "\n"]));
  await createLiveClient(BASE, { fetch }).sendMessage("exp-1", "hello", []);
  const body = calls[0].init.body as FormData;
  assert.equal(body.get("text"), "hello");
  assert.deepEqual(body.getAll("files"), []);
});

type Case = {
  name: string;
  call: (client: LabFactoryClient) => Promise<unknown>;
  method: string;
  path: string;
  body?: unknown;
};

const TARGET = { kind: "experiment", id: "exp-1" } as const;

const CASES: Case[] = [
  { name: "getLab", call: (c) => c.getLab("emory-biophys"), method: "GET", path: "/labs/emory-biophys" },
  { name: "listProjects", call: (c) => c.listProjects("emory-biophys"), method: "GET", path: "/labs/emory-biophys/projects" },
  { name: "getProject", call: (c) => c.getProject("coomassie"), method: "GET", path: "/projects/coomassie" },
  { name: "createProject", call: (c) => c.createProject("emory-biophys", "Dye kinetics", "Measure rates"),
    method: "POST", path: "/labs/emory-biophys/projects", body: { title: "Dye kinetics", goals: "Measure rates" } },
  { name: "createExperiment", call: (c) => c.createExperiment("coomassie", "Measure the rate", ["uvvis-1"]),
    method: "POST", path: "/projects/coomassie/experiments",
    body: { description: "Measure the rate", instrument_ids: ["uvvis-1"] } },
  { name: "getWorkspace", call: (c) => c.getWorkspace("exp-1"), method: "GET", path: "/experiments/exp-1/workspace" },
  { name: "getSubmissionView", call: (c) => c.getSubmissionView("WO-B12", 2), method: "GET",
    path: "/work-orders/WO-B12/submissions/2" },
  { name: "approve", call: (c) => c.approve("WO-B12", 2, "Dr Rivera"), method: "POST",
    path: "/work-orders/WO-B12/approve", body: { submission: 2, person: "Dr Rivera" } },
  { name: "reject", call: (c) => c.reject("WO-B12", 2, "Dr Rivera", "Use the 1 cm cuvette"), method: "POST",
    path: "/work-orders/WO-B12/reject", body: { submission: 2, person: "Dr Rivera", reason: "Use the 1 cm cuvette" } },
  { name: "needsAttention", call: (c) => c.needsAttention("emory-biophys", "approver"), method: "GET",
    path: "/labs/emory-biophys/attention?role=approver" },
  { name: "addDocument (project)", call: (c) => c.addDocument({ kind: "project", id: "coomassie" },
    { title: "Protocol", kind: "sop", text: "Step one" }), method: "POST", path: "/projects/coomassie/documents",
    body: { title: "Protocol", kind: "sop", text: "Step one" } },
  { name: "addDocument (experiment)", call: (c) => c.addDocument(TARGET, { title: "Notes", kind: "note", text: "x" }),
    method: "POST", path: "/experiments/exp-1/documents", body: { title: "Notes", kind: "note", text: "x" } },
  { name: "listRevisions (lab)", call: (c) => c.listRevisions("lab", "emory-biophys"), method: "GET",
    path: "/labs/emory-biophys/revisions" },
  { name: "listRevisions (project)", call: (c) => c.listRevisions("project", "coomassie"), method: "GET",
    path: "/projects/coomassie/revisions" },
  { name: "listRevisions (experiment)", call: (c) => c.listRevisions("experiment", "exp-1"), method: "GET",
    path: "/experiments/exp-1/revisions" },
  { name: "listRevisions (skill)", call: (c) => c.listRevisions("skill", "procedure-style"), method: "GET",
    path: "/skills/procedure-style/revisions" },
  { name: "getSettings", call: (c) => c.getSettings("emory-biophys"), method: "GET", path: "/labs/emory-biophys/settings" },
  { name: "updateSettings", call: (c) => c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: ["Dr Rivera"] } }),
    method: "PUT", path: "/labs/emory-biophys/settings", body: { sign_off: { mode: "listed", names: ["Dr Rivera"] } } },
  { name: "search", call: (c) => c.search("emory-biophys", "cuv & dye?"), method: "GET",
    path: "/labs/emory-biophys/search?q=cuv%20%26%20dye%3F" },
  { name: "listSkills", call: (c) => c.listSkills("emory-biophys"), method: "GET", path: "/labs/emory-biophys/skills" },
  { name: "saveSkill (create)", call: (c) => c.saveSkill("emory-biophys", { title: "Units", description: "d", body: "b" }),
    method: "POST", path: "/labs/emory-biophys/skills", body: { title: "Units", description: "d", body: "b" } },
  { name: "saveSkill (update)", call: (c) => c.saveSkill("emory-biophys",
    { id: "procedure-style", title: "Style", description: "d", body: "b" }),
    method: "PUT", path: "/labs/emory-biophys/skills/procedure-style", body: { title: "Style", description: "d", body: "b" } },
  { name: "setSkillEnabled", call: (c) => c.setSkillEnabled("emory-biophys", "plots", false), method: "POST",
    path: "/labs/emory-biophys/skills/plots/enabled", body: { enabled: false } },
  { name: "listConnectors", call: (c) => c.listConnectors("emory-biophys"), method: "GET",
    path: "/labs/emory-biophys/connectors" },
  { name: "connect", call: (c) => c.connect("emory-biophys", "google_drive", "Lab drive"), method: "POST",
    path: "/labs/emory-biophys/connectors/google_drive/connect", body: { account: "Lab drive" } },
  { name: "disconnect", call: (c) => c.disconnect("emory-biophys", "zotero"), method: "POST",
    path: "/labs/emory-biophys/connectors/zotero/disconnect" },
  { name: "importFromConnector", call: (c) => c.importFromConnector("emory-biophys", "zotero", "item/1", TARGET),
    method: "POST", path: "/labs/emory-biophys/connectors/zotero/items/item%2F1/import", body: { target: TARGET } },
  { name: "listAgentConnections", call: (c) => c.listAgentConnections("emory-biophys"), method: "GET",
    path: "/labs/emory-biophys/agents" },
  { name: "getAgentSetup", call: (c) => c.getAgentSetup("emory-biophys"), method: "GET",
    path: "/labs/emory-biophys/agent-setup" },
];

for (const { name, call, method, path, body } of CASES) {
  test(`${name} sends ${method} ${path}`, async () => {
    const reply = { ok: name };
    const { calls, fetch } = stub(() => json(200, reply));
    assert.deepEqual(await call(createLiveClient(BASE, { fetch })), reply);
    assert.equal(calls.length, 1);
    const { url, init } = calls[0];
    assert.equal(url, BASE + path);
    assert.equal(init.method, method);
    assert.equal(init.credentials, "include");
    assert.equal(header(init, "accept"), "application/json");
    if (body === undefined) {
      assert.equal(init.body, undefined);
      assert.equal(header(init, "content-type"), null);
    } else {
      assert.equal(header(init, "content-type"), "application/json");
      assert.deepEqual(JSON.parse(String(init.body)), body);
    }
  });
}

test("path segments are URI-encoded", async () => {
  const { calls, fetch } = stub(() => json(200, {}));
  await createLiveClient(BASE, { fetch }).getSubmissionView("WO/../x", 1);
  assert.equal(calls[0].url, `${BASE}/work-orders/WO%2F..%2Fx/submissions/1`);
});

test("a 2xx response that isn't JSON is refused", async () => {
  const { fetch } = stub(() => new Response("<html></html>", { status: 200 }));
  await assert.rejects(createLiveClient(BASE, { fetch }).getLab("emory-biophys"), (error: unknown) =>
    error instanceof ClientError && error.code === "refused" && error.message === "The Lab Factory service returned 200.");
});

test("the global fetch is used when none is given", async () => {
  const original = globalThis.fetch;
  const { calls, fetch } = stub(() => json(200, []));
  globalThis.fetch = fetch;
  try {
    await createLiveClient(BASE).listSkills("emory-biophys");
  } finally {
    globalThis.fetch = original;
  }
  assert.equal(calls[0].url, `${BASE}/labs/emory-biophys/skills`);
});
