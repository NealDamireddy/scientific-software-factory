import test from "node:test";
import assert from "node:assert/strict";
import {
  startRun,
  advance,
  createDraft,
  cancel,
  initialExperiments,
} from "./simulation.ts";
import { buildAgentContext, defaultExtensions } from "./extension-model.ts";

const draft = () =>
  createDraft("Measure B12 concentration", "B12 quantification");
const customSkill = {
  id: "note",
  name: "Sample identity",
  whenToUse: "After reading",
  instructions: "Compare sample IDs.",
};
const customConnector = {
  id: "store",
  name: "File store",
  description: "Illustrative measurements.",
  endpoint: "https://example.test/records",
};
const settings = () => ({
  ...defaultExtensions,
  skills: ["evidence", "calibration", "note"],
  connectors: ["store"],
  customSkills: [{ ...customSkill }],
  customConnectors: [{ ...customConnector }],
});
function finish(e) {
  while (e.status === "Running") e = advance(e);
  return e;
}

test("captures the current briefing and detached enabled resources at every start", () => {
  const config = settings(),
    context = buildAgentContext(config);
  let e = startRun(draft(), "original", context);
  const first = e.runs[0].agentContext;
  assert.equal(first.briefing.objective, e.title);
  assert.equal(first.briefing.project, e.project);
  assert.equal(first.briefing.method.wavelengthNm, 361);
  context.skills.find((s) => s.id === "note").instructions =
    "Changed after run";
  config.customConnectors[0].description = "Renamed later";
  assert.deepEqual(
    first.skills.find((s) => s.id === "note"),
    customSkill,
  );
  assert.deepEqual(first.connectors[0], customConnector);
  e = finish(e);
  assert.deepEqual(
    e.runs[0].agentChecks.map((c) => c.skillId),
    ["calibration", "evidence"],
  );
  assert.match(
    e.runs[0].agentChecks[0].finding,
    /1.250 AU against 0.050–0.850 AU/,
  );
  config.skills = ["note"];
  config.connectors = [];
  const repeat = finish(startRun(e, "repeat", buildAgentContext(config)));
  assert.deepEqual(repeat.runs[1].agentChecks, []);
  assert.deepEqual(repeat.runs[1].agentContext.skills, [customSkill]);
  assert.equal(repeat.runs[1].agentContext.briefing.mode, "repeat");
  assert.deepEqual(repeat.runs[0], e.runs[0]);
  const replay = startRun(
    repeat,
    "original",
    buildAgentContext({ ...config, skills: [] }),
  );
  assert.equal(replay.runs[2].agentContext.skills.length, 0);
  assert.deepEqual(replay.runs[1], repeat.runs[1]);
});

test("only applicable enabled builtins produce a simulated finding", () => {
  const config = buildAgentContext(defaultExtensions);
  const e = finish(startRun(draft(), "original", config));
  const repeat = finish(startRun(e, "repeat", config));
  assert.match(repeat.runs[1].agentChecks[0].finding, /0.650 AU/);
  assert.match(repeat.runs[1].agentChecks[0].finding, /within range/);
  assert.match(
    repeat.runs[1].agentChecks[1].finding,
    /6 calibration standards/,
  );
  const kinetic = finish(
    startRun(
      createDraft("Time course", "Coomassie reduction"),
      "original",
      config,
    ),
  );
  assert.deepEqual(
    kinetic.runs[0].agentChecks.map((c) => c.skillId),
    ["evidence"],
  );
  assert.match(kinetic.runs[0].agentChecks[0].finding, /9 time points/);
});

test("partial runs retain context without findings, older snapshots remain absent", () => {
  const e = cancel(
    advance(
      startRun(draft(), "original", buildAgentContext(defaultExtensions)),
    ),
  );
  assert.ok(e.runs[0].agentContext);
  assert.deepEqual(e.runs[0].agentChecks, []);
  for (const old of initialExperiments)
    for (const run of old.runs) assert.equal(run.agentContext, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(e)), e);
});
