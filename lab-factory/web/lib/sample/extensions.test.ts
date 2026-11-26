import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { canonicalDigest } from "../digest.ts";
import { ClientError } from "../types.ts";
import { AGENT_SETUP, SKILL_MD } from "./agent-setup.ts";
import { createSampleClient } from "./client.ts";
import { enabledSkillPins, enabledSkills } from "./extensions.ts";
import { createSeed } from "./seed.ts";

const LAB = "emory-biophys";
const NOW = new Date("2026-11-26T12:00:00.000Z");
const fresh = () => createSampleClient({ now: () => NOW });
const ago = (minutes: number): string => new Date(NOW.getTime() - minutes * 60_000).toISOString();

async function rejects(promise: Promise<unknown>, code: string, message?: string): Promise<void> {
  await assert.rejects(promise, (error) => {
    assert.ok(error instanceof ClientError, String(error));
    assert.equal(error.code, code);
    if (message !== undefined) assert.equal(error.message, message);
    return true;
  });
}

// ---------------------------------------------------------------- skills

test("listSkills returns the 3 seeded skills in seed order", async () => {
  const skills = await fresh().listSkills(LAB);
  assert.deepEqual(skills.map((s) => [s.id, s.title, s.enabled, s.revision]), [
    ["procedure-style", "How we write procedures", true, 1],
    ["reporting-units", "Units we report in", true, 1],
    ["plot-style", "Plotting conventions", false, 1],
  ]);
  await rejects(fresh().listSkills("nope"), "not_found");
});

test("editing a skill makes revision 2, and saving identical content keeps revision 2", async () => {
  const c = fresh();
  const [skill] = await c.listSkills(LAB);
  const body = `${skill.body}\n- Number every step.`;
  const edited = await c.saveSkill(LAB, { id: skill.id, title: ` ${skill.title} `, description: skill.description, body });
  assert.equal(edited.revision, 2);
  assert.equal(edited.title, "How we write procedures");
  assert.equal(edited.body, body);
  assert.equal(edited.enabled, true);
  const again = await c.saveSkill(LAB, { id: skill.id, title: skill.title, description: ` ${skill.description}`, body });
  assert.equal(again.revision, 2);
  const revisions = await c.listRevisions("skill", skill.id);
  assert.deepEqual(revisions.map((r) => [r.number, r.note]), [[1, "Created"], [2, "Edited"]]);
  assert.equal(revisions[1].at, NOW.toISOString());
  assert.equal(revisions[1].digest, await canonicalDigest({ id: skill.id, title: skill.title, description: skill.description, body }));
  assert.equal((await c.listSkills(LAB))[0].revision, 2);
});

test("seeded skill digests match the digest saveSkill computes", async () => {
  const c = fresh();
  const [skill] = await c.listSkills(LAB);
  const { enabled: _e, revision: _r, ...record } = skill;
  assert.equal((await c.listRevisions("skill", skill.id))[0].digest, await canonicalDigest(record));
});

test("overlapping identical edits make one revision", async () => {
  const c = fresh();
  const [skill] = await c.listSkills(LAB);
  const input = { id: skill.id, title: skill.title, description: skill.description, body: "- New body." };
  const results = await Promise.all([c.saveSkill(LAB, input), c.saveSkill(LAB, input), c.saveSkill(LAB, input)]);
  assert.deepEqual(results.map((s) => s.revision), [2, 2, 2]);
  assert.equal((await c.listRevisions("skill", skill.id)).length, 2);
});

test("creating a skill slugs its title, enables it and records revision 1", async () => {
  const c = fresh();
  const created = await c.saveSkill(LAB, { title: "How we write procedures", description: " Again ", body: "- Be brief." });
  assert.deepEqual(created, {
    id: "how-we-write-procedures", title: "How we write procedures", description: "Again", body: "- Be brief.",
    enabled: true, revision: 1,
  });
  const second = await c.saveSkill(LAB, { title: "How we write procedures", description: "", body: "- Be briefer." });
  assert.equal(second.id, "how-we-write-procedures-2");
  assert.deepEqual((await c.listRevisions("skill", created.id)).map((r) => [r.number, r.note]), [[1, "Created"]]);
  assert.equal((await c.listSkills(LAB)).length, 5);
});

test("saveSkill rejects blank fields and unknown ids", async () => {
  const c = fresh();
  await rejects(c.saveSkill(LAB, { title: "  ", description: "", body: "- x" }), "invalid");
  await rejects(c.saveSkill(LAB, { title: "Title", description: "", body: " \n " }), "invalid");
  await rejects(c.saveSkill(LAB, { id: "procedure-style", title: "", description: "", body: "- x" }), "invalid");
  await rejects(c.saveSkill(LAB, { id: "nope", title: "Title", description: "", body: "- x" }), "not_found");
  await rejects(c.saveSkill("nope", { title: "Title", description: "", body: "- x" }), "not_found");
});

test("toggling a skill doesn't change its revision", async () => {
  const c = fresh();
  const on = await c.setSkillEnabled(LAB, "plot-style", true);
  assert.equal(on.enabled, true);
  assert.equal(on.revision, 1);
  assert.equal((await c.setSkillEnabled(LAB, "plot-style", false)).enabled, false);
  assert.equal((await c.listRevisions("skill", "plot-style")).length, 1);
  await rejects(c.setSkillEnabled(LAB, "nope", true), "not_found");
});

test("returned skills are copies", async () => {
  const c = fresh();
  const skills = await c.listSkills(LAB);
  skills[0].title = "Changed";
  const saved = await c.setSkillEnabled(LAB, "plot-style", true);
  saved.enabled = false;
  const again = await c.listSkills(LAB);
  assert.equal(again[0].title, "How we write procedures");
  assert.equal(again[2].enabled, true);
});

test("enabledSkills and enabledSkillPins follow seed order and the latest revision", async () => {
  const state = await createSeed(NOW);
  assert.deepEqual(enabledSkills(state).map((s) => s.title), ["How we write procedures", "Units we report in"]);
  const pins = enabledSkillPins(state);
  assert.deepEqual(pins.map((p) => [p.kind, p.id, p.revision]), [["skill", "procedure-style", 1], ["skill", "reporting-units", 1]]);
  assert.deepEqual(pins, state.orders[0].pins.filter((p) => p.kind === "skill"));
});

// ---------------------------------------------------------------- connectors

test("listConnectors shows Zotero items and none for Google Drive", async () => {
  const connectors = await fresh().listConnectors(LAB);
  assert.deepEqual(connectors.map((x) => x.id), ["google_drive", "zotero", "eln", "instrument_folder", "github"]);
  const drive = connectors.find((x) => x.id === "google_drive")!;
  assert.equal(drive.connected, false);
  assert.equal(drive.account, null);
  assert.deepEqual(drive.items, []);
  const zotero = connectors.find((x) => x.id === "zotero")!;
  assert.equal(zotero.account, "Emory Biophysics library");
  assert.deepEqual(zotero.items.map((i) => i.id), ["zotero-dye-reduction"]);
});

test("importing from Google Drive needs a connection, then adds a project document", async () => {
  const c = fresh();
  const target = { kind: "project" as const, id: "coomassie-reduction" };
  await rejects(c.importFromConnector(LAB, "google_drive", "drive-dye-protocol", target), "refused", "Connect Google Drive first.");
  await rejects(c.connect(LAB, "google_drive", "   "), "invalid");
  const connected = await c.connect(LAB, "google_drive", " Lab drive ");
  assert.equal(connected.connected, true);
  assert.equal(connected.account, "Lab drive");
  assert.deepEqual(connected.items.map((i) => i.id), ["drive-dye-protocol"]);

  const revision = await c.importFromConnector(LAB, "google_drive", "drive-dye-protocol", target);
  assert.equal(revision.number, 2);
  assert.equal(revision.note, "Added Coomassie dye protocol (sample)");
  const project = await c.getProject("coomassie-reduction");
  const added = project.documents.at(-1)!;
  assert.deepEqual(added, {
    id: "coomassie-dye-protocol-sample", kind: "sop", title: "Coomassie dye protocol (sample)",
    source: "Google Drive: Lab drive", text: "Dissolve the dye in the buffer, filter it, and store it in the dark.",
  });
  // The same item again returns the latest revision unchanged.
  assert.equal((await c.importFromConnector(LAB, "google_drive", "drive-dye-protocol", target)).number, 2);
});

test("code items become notes on an experiment", async () => {
  const c = fresh();
  await c.connect(LAB, "github", "lab/analysis");
  const revision = await c.importFromConnector(LAB, "github", "gh-fit-utils", { kind: "experiment", id: "coomassie-run-1" });
  assert.equal(revision.number, 2);
  const doc = (await c.getWorkspace("coomassie-run-1")).experiment.documents.at(-1)!;
  assert.equal(doc.kind, "note");
  assert.equal(doc.source, "GitHub: lab/analysis");
});

test("importing a readings item is invalid", async () => {
  await rejects(
    fresh().importFromConnector(LAB, "instrument_folder", "coomassie-run-1.csv", { kind: "experiment", id: "coomassie-run-1" }),
    "invalid", "Readings go to an experiment's Results tab.",
  );
});

test("import and connect reject unknown connectors, items and targets", async () => {
  const c = fresh();
  const target = { kind: "project" as const, id: "coomassie-reduction" };
  await rejects(c.importFromConnector(LAB, "nope" as never, "x", target), "not_found");
  await rejects(c.importFromConnector(LAB, "zotero", "nope", target), "not_found");
  await rejects(c.importFromConnector(LAB, "zotero", "zotero-dye-reduction", { kind: "project", id: "nope" }), "not_found");
  await rejects(c.importFromConnector(LAB, "zotero", "zotero-dye-reduction", { kind: "experiment", id: "nope" }), "not_found");
  await rejects(c.importFromConnector("nope", "zotero", "zotero-dye-reduction", target), "not_found");
  await rejects(c.connect(LAB, "nope" as never, "x"), "not_found");
  await rejects(c.disconnect(LAB, "nope" as never), "not_found");
  await rejects(c.listConnectors("nope"), "not_found");
});

test("disconnect clears the account and hides items", async () => {
  const c = fresh();
  const off = await c.disconnect(LAB, "zotero");
  assert.equal(off.connected, false);
  assert.equal(off.account, null);
  assert.deepEqual(off.items, []);
  const zotero = (await c.listConnectors(LAB)).find((x) => x.id === "zotero")!;
  assert.deepEqual([zotero.connected, zotero.account, zotero.items], [false, null, []]);
  await rejects(
    c.importFromConnector(LAB, "zotero", "zotero-dye-reduction", { kind: "project", id: "coomassie-reduction" }),
    "refused", "Connect Zotero first.",
  );
});

// ---------------------------------------------------------------- search

test("search finds skills and connectors after the other kinds", async () => {
  const c = fresh();
  assert.deepEqual(await c.search(LAB, "plot"), [
    { kind: "skill", id: "plot-style", title: "Plotting conventions", href: "#/skills?skill=plot-style" },
  ]);
  assert.deepEqual(await c.search(LAB, "zot"), [
    { kind: "connector", id: "zotero", title: "Zotero", href: "#/connectors" },
  ]);
  assert.deepEqual((await c.search(LAB, "google_drive")).map((h) => h.id), ["google_drive"]);
  const procedure = await c.search(LAB, "procedure");
  assert.deepEqual(procedure.map((h) => h.kind), ["skill"]);
  assert.equal(procedure[0].id, "procedure-style");
  const kinds = (await c.search(LAB, "e")).map((h) => h.kind);
  const order = ["project", "experiment", "document", "instrument", "skill", "connector"];
  assert.deepEqual(kinds, [...kinds].sort((a, b) => order.indexOf(a) - order.indexOf(b)));
  assert.ok(kinds.length <= 20);
});

// ---------------------------------------------------------------- agents

test("listAgentConnections comes from claim events, newest first", async () => {
  const c = fresh();
  assert.deepEqual(await c.listAgentConnections(LAB), [
    { worker: "factory", last_seen: ago(87), work_order_ids: ["WO-1"] },
    { worker: "codex on lab-pc", last_seen: ago(185), work_order_ids: ["WO-B12-RP", "WO-B12"] },
  ]);
  await rejects(c.listAgentConnections("nope"), "not_found");
});

test("SKILL_MD equals the file on disk and covers the loop and sign-off", () => {
  const file = readFileSync(join(import.meta.dirname, "../../public/skills/labfactory-work-orders/SKILL.md"), "utf8");
  assert.equal(SKILL_MD, file);
  assert.match(SKILL_MD, /^---\nname: labfactory-work-orders\ndescription: Use when working Lab Factory work orders over MCP/);
  for (const name of ["list_work_orders", "claim_work_order", "get_work_order_context", "submit_artifact"]) {
    assert.ok(SKILL_MD.includes(name), name);
  }
  for (const heading of ["## The loop", "## Rules", "## Sign-off"]) assert.ok(SKILL_MD.includes(`\n${heading}\n`), heading);
  const signOff = SKILL_MD.slice(SKILL_MD.indexOf("## Sign-off"));
  assert.ok(signOff.includes("Only a person can sign off a submission. Agents cannot approve or release work."));
});

test("AGENT_SETUP tool descriptions equal the docstrings in mcp_server.py", () => {
  const source = readFileSync(join(import.meta.dirname, "../../../src/labfactory/mcp_server.py"), "utf8");
  const docstrings = [...source.matchAll(/def (\w+)\([^)]*\)[^:]*:\s*"""([^"]+)"""/g)].map((m) => ({ name: m[1], description: m[2] }));
  assert.equal(docstrings.length, 4);
  const byName = (tools: { name: string; description: string }[]) => [...tools].sort((a, b) => a.name.localeCompare(b.name));
  assert.deepEqual(byName(AGENT_SETUP.tools), byName(docstrings));
  assert.deepEqual(AGENT_SETUP.tools.map((t) => t.name), ["list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact"]);
});

test("AGENT_SETUP commands are exact, and Cursor's args match Codex's", async () => {
  assert.equal(AGENT_SETUP.claude_code,
    'claude mcp add labfactory -- uv run --locked --project "/absolute/path/to/lab-factory" labfactory --db "/absolute/path/to/labfactory.db" serve');
  assert.equal(AGENT_SETUP.codex_toml, [
    "[mcp_servers.labfactory]",
    'command = "uv"',
    'args = ["run", "--locked", "--project", "/absolute/path/to/lab-factory", "labfactory", "--db", "/absolute/path/to/labfactory.db", "serve"]',
  ].join("\n"));
  const codexArgs = JSON.parse(AGENT_SETUP.codex_toml.split("\n")[2].replace(/^args = /, ""));
  assert.equal(codexArgs.length, 8);
  const cursor = JSON.parse(AGENT_SETUP.cursor_json);
  assert.deepEqual(cursor, { mcpServers: { labfactory: { command: "uv", args: codexArgs } } });
  assert.equal(AGENT_SETUP.cursor_json, JSON.stringify(cursor, null, 2));
  assert.equal(AGENT_SETUP.skill_md, SKILL_MD);

  const c = fresh();
  const setup = await c.getAgentSetup(LAB);
  assert.deepEqual(setup, AGENT_SETUP);
  setup.tools[0].description = "changed";
  assert.equal((await c.getAgentSetup(LAB)).tools[0].description, "List work orders with the given status.");
  await rejects(c.getAgentSetup("nope"), "not_found");
});
