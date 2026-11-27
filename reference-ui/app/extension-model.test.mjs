import assert from "node:assert/strict";
import test from "node:test";
import {
  buildAgentContext,
  builtinSkills,
  defaultExtensions,
  normalizeExtensions,
} from "./extension-model.ts";

const harness = {
  name: "Research harness",
  endpoint: "http://localhost:8100/context",
};
const connector = {
  id: "lab-vault",
  name: "Lab vault",
  endpoint: "https://vault.example.test/records",
  description: "Read archived demo records.",
};
const skill = {
  id: "crosscheck",
  name: "Cross-check",
  whenToUse: "After a repeat",
  instructions: "Compare both run IDs.\nPreserve units.",
};

test("migrates saved selections and harness without activating new resources", () => {
  assert.deepEqual(
    normalizeExtensions({ harness, connectors: ["archive"], skills: [] }),
    {
      harness,
      connectors: ["archive"],
      skills: [],
      customConnectors: [],
      customSkills: [],
    },
  );
  assert.deepEqual(normalizeExtensions(undefined), defaultExtensions);
});

test("handoff exports full enabled content, selected endpoints and explicit authority", () => {
  const state = {
    harness,
    customConnectors: [connector],
    customSkills: [skill],
    connectors: ["notebook", connector.id],
    skills: ["method", skill.id],
  };
  const ctx = buildAgentContext(state);
  assert.deepEqual(
    [ctx.schemaVersion, ctx.simulationOnly, ctx.executionAuthority],
    [1, true, "none"],
  );
  assert.deepEqual(ctx.harness, harness);
  assert.deepEqual(
    ctx.connectors.map((c) => c.id),
    ["notebook", connector.id],
  );
  assert.deepEqual(ctx.connectors[1], connector);
  assert.deepEqual(
    ctx.skills.map((s) => s.id),
    ["method", skill.id],
  );
  assert.equal(
    ctx.skills[0].instructions,
    builtinSkills.find((s) => s.id === "method").instructions,
  );
  assert.deepEqual(ctx.skills[1], skill);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx)), ctx);
});

test("disabled content and removed records are absent from the handoff", () => {
  const ctx = buildAgentContext({
    harness: null,
    customConnectors: [connector],
    customSkills: [skill],
    connectors: ["missing"],
    skills: [],
  });
  assert.deepEqual(ctx.connectors, []);
  assert.deepEqual(ctx.skills, []);
  assert.equal(ctx.harness, null);
});

test("renaming keeps the identity and exports the new display name and edited content", () => {
  const updated = {
    ...skill,
    name: "Run audit",
    instructions: "Use the latest annotated repeat.",
  };
  const state = {
    ...defaultExtensions,
    customConnectors: [{ ...connector, name: "Renamed archive" }],
    connectors: [connector.id],
    customSkills: [updated],
    skills: [skill.id],
  };
  const ctx = buildAgentContext(state);
  assert.equal(ctx.connectors[0].name, "Renamed archive");
  assert.deepEqual(ctx.skills, [updated]);
});

test("malformed local records and collisions cannot overwrite built-in entries", () => {
  const state = normalizeExtensions({
    harness: {
      ...harness,
      endpoint: "https://user:password@example.test/secret",
    },
    customConnectors: [{ ...connector, id: "archive" }, null],
    customSkills: [skill, skill, { id: 2 }],
    connectors: ["archive", "archive", "missing"],
    skills: [skill.id, skill.id],
  });
  assert.equal(state.harness, null);
  assert.deepEqual(state.customConnectors, []);
  assert.deepEqual(state.customSkills, [skill]);
  assert.deepEqual(state.skills, [skill.id]);
  assert.deepEqual(state.connectors, ["archive"]);
});
