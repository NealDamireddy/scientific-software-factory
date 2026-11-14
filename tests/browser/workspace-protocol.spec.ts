import { test as base, expect } from "playwright/test";
import { createFixtureClient } from "../../app/workspace/fixture";

const test = base.extend<{ store: Map<string, string> }>({
  store: async ({}, use) => {
    const store = new Map<string, string>();
    const original = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
      },
    });
    try {
      await use(store);
    } finally {
      if (original) Object.defineProperty(globalThis, "sessionStorage", original);
      else Reflect.deleteProperty(globalThis, "sessionStorage");
    }
  },
});

test("fixture rejects forged protocol fields at save, approval and submission", async ({ store }) => {
  const api = createFixtureClient();
  const id = "visible-assay";
  const spec = (await api.read(id)).specifications[0];
  for (const override of [
    { outputs: ["invented_output"] },
    { validation_criteria: ["No numerical checks required"] },
    { units: { ...spec.units, concentration: "mol/L" } },
  ]) {
    await expect(api.saveSpecification(id, { ...spec, ...override }, spec.revision)).rejects.toMatchObject({
      status: 422,
    });
  }
  expect((await api.read(id)).specifications).toHaveLength(2);
  // Simulate a record persisted by the previous fixture implementation.
  const [key, raw] = Array.from(store.entries())[0];
  const saved = JSON.parse(raw);
  saved.snapshot.specifications[0].outputs = ["invented_output"];
  store.set(key, JSON.stringify(saved));
  await expect(api.submit(id, spec, "retry")).rejects.toMatchObject({
    status: 422,
  });
  saved.snapshot.specifications[0].approval = null;
  saved.snapshot.specifications[0].status = "draft";
  store.set(key, JSON.stringify(saved));
  await expect(api.approve(id, spec, spec.approval!.confirmed_fields)).rejects.toMatchObject({ status: 422 });
});

test("fixture retains lineage pins and starts independent specifications on selected historical revisions", async ({
  store,
}) => {
  expect(store.size).toBe(0);
  const api = createFixtureClient();
  const id = "visible-assay";
  const state = await api.read(id);
  const spec = state.specifications[0];
  const lab = await api.saveLab(id, { ...state.labs[0].payload, name: "Renamed lab" }, 1);
  const project = await api.saveProject(id, state.projects[0].payload, 1);
  expect(project.sha256).toBe(spec.project.sha256);
  const nextPins = {
    lab: { ...spec.lab, revision: lab.revision, sha256: lab.sha256 },
    project: {
      ...spec.project,
      revision: project.revision,
      sha256: project.sha256,
    },
  };

  for (const replacement of [
    nextPins,
    { lab: { ...spec.lab, project_id: id } },
    { project: { ...spec.project, lab_id: "another-lab" } },
    { instrument: { ...spec.instrument, profile_sha256: "different" } },
  ]) {
    await expect(api.saveSpecification(id, { ...spec, ...replacement }, 1)).rejects.toMatchObject({
      status: 409,
    });
  }

  await expect(api.saveSpecification(id, { ...spec, specification_id: "unknown" }, 0)).rejects.toMatchObject({
    status: 404,
  });
  const historical = await api.saveSpecification(id, { ...spec, specification_id: undefined }, 0);
  expect(historical.specification_id).not.toBe(spec.specification_id);
  expect(historical).toMatchObject({
    revision: 1,
    lab: spec.lab,
    project: spec.project,
    instrument: spec.instrument,
    approval: null,
  });
  const fresh = await api.saveSpecification(id, { ...spec, ...nextPins, specification_id: undefined }, 0);
  expect(fresh.specification_id).not.toBe(spec.specification_id);
  expect(fresh).toMatchObject({ ...nextPins, revision: 1, approval: null });

  const edit = await api.saveSpecification(id, { ...spec, sample_ids: ["vial-alt"] }, 1);
  expect(edit).toMatchObject({
    specification_id: spec.specification_id,
    revision: 2,
    lab: spec.lab,
    project: spec.project,
    instrument: spec.instrument,
    status: "draft",
    approval: null,
  });
  await expect(api.submit(id, edit, "unapproved")).rejects.toMatchObject({
    status: 422,
  });
  const approved = await api.approve(id, edit, spec.approval!.confirmed_fields);
  expect(approved.approval?.specification_sha256).toBe(edit.sha256);
  expect(edit.sha256).not.toBe(spec.sha256);
  expect((await api.read(id)).specifications.find((s) => s.sha256 === spec.sha256)).toEqual(spec);
  // A prior fixture version could persist a later revision with replacement pins.
  const [key, raw] = Array.from(store.entries())[0];
  const saved = JSON.parse(raw);
  Object.assign(
    saved.snapshot.specifications.find((s: { sha256: string }) => s.sha256 === edit.sha256),
    nextPins,
  );
  store.set(key, JSON.stringify(saved));
  await expect(api.submit(id, approved, "legacy")).rejects.toMatchObject({ status: 409 });
  await expect(api.approve(id, approved, spec.approval!.confirmed_fields)).rejects.toMatchObject({
    status: 409,
  });
  await expect(api.saveSpecification(id, { ...approved, ...nextPins }, 2)).rejects.toMatchObject({
    status: 409,
  });
  await expect(api.submit(id, spec, "original")).resolves.toHaveProperty("run_id");
});
