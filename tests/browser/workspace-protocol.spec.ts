import { test as base, expect } from "playwright/test";
import golden from "../../fixtures/workspace/producer-records.json";
import { digest } from "../../app/workspace/fixture-provenance";
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
  expect((await api.read(id)).specifications).toHaveLength(golden.specifications.length);
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

test("fixture saves unresolved scientific fields and revalidates persisted drafts at approval", async ({store}) => {
  expect(store.size).toBe(0);
  const api = createFixtureClient();
  const project = "visible-assay";
  const {specifications} = await api.read(project);
  const [concentration, course] = specifications.filter(spec => spec.status === "approved");
  for (const [spec, overrides, path] of [
    [concentration, {schedule: {interval_s: 2, point_count: 3}}, "schedule"],
    [course, {standards: concentration.standards}, "standards"],
    [concentration, {settings: {...concentration.settings, operation:"scan"}}, "settings.operation"],
    [concentration, {calibration: {...course.calibration!, sha256:"0".repeat(64)}}, "calibration"],
  ] as const) {
    const draft = await api.saveSpecification(project, {...spec, ...overrides, specification_id: undefined}, 0);
    expect(draft.approval).toBeNull();
    expect(draft.unresolved_fields?.[path]).toBeTruthy();
    await expect(api.approve(project, draft, spec.approval!.confirmed_fields)).rejects.toMatchObject({
      status:422, fields:{[path]: expect.any(String)},
    });
    await expect(api.submit(project, draft, "blocked")).rejects.toMatchObject({status:422});
  }
});

test("fixture rejects duplicate context values and invalid protocol identifiers", async ({store}) => {
  expect(store.size).toBe(0);
  const api = createFixtureClient();
  const id = "visible-assay";
  const {projects, labs} = await api.read(id);
  const lab = labs[0].payload;
  const project = projects[0].payload;
  for (const key of ["approved_libraries", "operating_restrictions"] as const) {
    await expect(api.saveLab(id, {...lab, [key]:["repeated","repeated"]}, 1)).rejects.toMatchObject({
      status:422, fields:{[key]:expect.any(String)},
    });
  }
  await expect(api.saveProject(id, {...project, validation_criteria:["repeated", "repeated"]}, 1))
    .rejects.toMatchObject({status:422, fields:{validation_criteria:expect.any(String)}});
  await expect(api.saveProject(id, {...project, protocol_id:"protocol with spaces"}, 1))
    .rejects.toMatchObject({status:422, fields:{protocol_id:expect.any(String)}});
});

test("approval targets the selected immutable revision after a subsequent edit", async ({store}) => {
  expect(store.size).toBe(0);
  const api = createFixtureClient();
  const project = "visible-assay";
  const template = (await api.read(project)).specifications[0];
  const original = await api.saveSpecification(project, {...template, specification_id:undefined}, 0);
  const revised = await api.saveSpecification(project, {...original, sample_ids:["sample-after-edit"]}, 1);
  const approved = await api.approve(project, original, template.approval!.confirmed_fields);
  expect(approved.approval?.specification_sha256).toBe(original.sha256);
  expect((await api.read(project)).specifications.find((s) => s.sha256 === revised.sha256)?.approval).toBeNull();
  await expect(api.submit(project, revised, "pending")).rejects.toMatchObject({status:422});
});

test("workspace projections, approvals and exported evidence resolve to complete records", async ({ store }) => {
  expect(store.size).toBe(0);
  const api = createFixtureClient();
  const id = "visible-assay";
  const snapshot = await api.read(id);
  for (const captured of golden.specifications) {
    const spec = snapshot.specifications.find(item => item.sha256 === captured.sha256)!;
    if (!captured.approval) {
      expect(spec.status).toBe("draft");
      expect(spec.unresolved_fields).toEqual(captured.unresolved_fields);
      expect(snapshot.runs.some(run => run.spec_digest === spec.sha256)).toBe(false);
      continue;
    }
    const run = snapshot.runs.find(item => item.spec_digest === spec.sha256)!;
    expect(spec.sha256).toBe(captured.sha256);
    expect(spec.approval).toEqual(captured.approval);
    expect(spec.approval?.specification_sha256).toBe(run.spec_digest);
    const report = JSON.parse(await (await api.evidence(id, run.run_id)).text());
    expect(report.specification_record).toEqual({origin:"producer", payload:captured.payload});
    expect(await digest(report.specification_record.payload)).toBe(spec.sha256);
    expect(report.calibration).toEqual(golden.calibration);
    expect(await digest(report.calibration.payload)).toBe(report.calibration.reference.sha256);
    if (spec.experiment_type === "time_course") {
      expect(spec.calibration).toEqual(report.calibration.reference);
      const {sha256, ...referenceMetadata} = spec.calibration!;
      expect(await digest(referenceMetadata)).not.toBe(sha256);
    }
  }
  const original = snapshot.specifications[0];
  const edit = await api.saveSpecification(id, {...original, sample_ids:["updated-vial"]}, original.revision);
  const approved = await api.approve(id, edit, original.approval!.confirmed_fields);
  const run = await api.submit(id, approved, "edited-spec");
  const report = JSON.parse(await (await api.evidence(id, run.run_id)).text());
  expect(report.specification_record.origin).toBe("fixture-session");
  expect(report.specification_record.payload).toEqual({...golden.specifications[0].payload,
    sample_ids:["updated-vial"], revision:2});
  expect(await digest(report.specification_record.payload)).toBe(approved.sha256);
});

test("changed projection, record or approval cannot authorize an unchanged digest", async ({store}) => {
  const id = "visible-assay";
  const api = createFixtureClient();
  const snapshot = await api.read(id);
  const original = snapshot.specifications[0];
  const draft = await api.saveSpecification(id, {...original, sample_ids:["edited-vial"]}, original.revision);
  const edited = await api.approve(id, draft, original.approval!.confirmed_fields);
  const submitted = await api.submit(id, edited, "before-tampering");
  const [key, clean] = Array.from(store.entries())[0];
  for (const [spec, runId] of [[original, snapshot.runs[0].run_id], [edited, submitted.run_id]] as const) {
    for (const tamper of ["projection", "payload", "approval"]) {
      const state = JSON.parse(clean);
      const view = state.snapshot.specifications.find((item: {sha256:string}) => item.sha256 === spec.sha256);
      if (tamper === "projection") view.sample_ids = ["different-valid-vial"];
      if (tamper === "payload") state.specification_records[spec.sha256].payload.scientific_objective = "Another goal";
      if (tamper === "approval") view.approval.specification_sha256 = edited.sha256 + "0";
      store.set(key, JSON.stringify(state));
      await expect(api.evidence(id, runId)).rejects.toMatchObject({status:409});
      await expect(api.submit(id, spec, "changed-record")).rejects.toThrow();
      if (spec === edited) await expect(api.approve(id, spec, spec.approval!.confirmed_fields)).rejects.toMatchObject({status:409});
    }
  }
});


test("an authentic calibration from another project cannot authorize a draft", async ({store}) => {
  const api = createFixtureClient();
  const owner = await api.read("visible-assay");
  const course = owner.specifications.find(spec => spec.experiment_type === "time_course" && spec.approval)!;
  const scope = await api.read("empty-assay");
  const key = Array.from(store.keys()).find(k => k.endsWith("/empty-assay"))!;
  const persisted = JSON.parse(store.get(key)!);
  persisted.snapshot.calibrations.push(course.calibration);
  store.set(key, JSON.stringify(persisted));
  const project = {...course.project, project_id:scope.project_id, sha256:scope.projects[0].sha256};
  const draft = await api.saveSpecification(scope.project_id, {...course, project, specification_id:undefined}, 0);
  expect(draft.unresolved_fields?.calibration).toBeTruthy();
  await expect(api.approve(scope.project_id, draft, course.approval!.confirmed_fields)).rejects.toMatchObject({
    status:422, fields:{calibration:expect.any(String)}
  });
});
