import { test as base, expect } from "playwright/test";
import { readFile, readdir } from "node:fs/promises";
import {
  currentRun, pipelineStages, runLabel, untestedInstrument, verificationHeadline,
} from "../../app/evidence.mjs";
import {
  checkManifest, checkSourceRevision, metricsPass, replayScope, sha256Hex,
} from "../../public/replay-checks.mjs";
import { approvalMatches, verifiedResult, type Run } from "../../app/workspace/api";
import { createFixtureClient } from "../../app/workspace/fixture";

const test = base.extend<{ storage: void }>({
  storage: async ({}, use) => {
    const store = new Map<string, string>();
    const original = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v) },
    });
    try { await use(); } finally {
      if (original) Object.defineProperty(globalThis, "sessionStorage", original);
      else Reflect.deleteProperty(globalThis, "sessionStorage");
    }
  },
});

async function evidence() {
  const runs = [];
  for (const project of await readdir("public/evidence"))
    for (const id of await readdir("public/evidence/" + project))
      runs.push({ report: JSON.parse(await readFile(`public/evidence/${project}/${id}/report.json`, "utf8")) });
  return runs.sort((a, b) => b.report.created_utc.localeCompare(a.report.created_utc));
}
const check = (name: string, status: string, category = "data") => ({ name, status, category, detail: name + " detail." });
const report = (checks: object[], extra: object = {}) => ({
  id: "r", project: "p", status: "failed", source_revision: "abc", checks, tests: [], ...extra,
});

test("run labels, pipeline and headline come from the recorded checks", async () => {
  const labels = Object.fromEntries((await evidence()).map(({ report }) => [report.id, runLabel(report)]));
  expect(labels["20261114T041110Z-5bbb0ad5"]).toBe("Input units failed");
  expect(labels["20261114T041110Z-8ef9fd62"]).toBe("Pulse acquisition failed");
  expect(labels["20261114T041110Z-b188b519"]).toBe("4 of 4 independent analytic cases passed");
  expect(labels["20261114T041110Z-d3017eff"]).toBe("3 of 3 independent analytic cases passed");

  // A run that failed at Verify must not be drawn as a preflight failure.
  const atVerify = report([check("units", "pass"), check("execution", "pass", "software"),
    check("reference", "fail", "numerical"), check("physical instrument", "untested", "real instrument")]);
  expect(runLabel(atVerify)).toBe("Numerical references failed");
  expect(pipelineStages(atVerify).map(s => s.state)).toEqual(["pass", "pass", "pass", "pass", "fail"]);
  expect(verificationHeadline(atVerify)).toEqual({
    title: "Run failed at verify", detail: "Numerical references: reference detail.",
  });

  const atExecute = report([check("units", "pass"), check("execution", "fail", "software"),
    check("reference", "untested", "numerical")]);
  expect(pipelineStages(atExecute).map(s => s.state)).toEqual(["pass", "pass", "pass", "fail", "skipped"]);

  const atPreflight = report([check("units", "fail"), check("execution", "untested", "software")],
    { status: "blocked", source_revision: null });
  expect(pipelineStages(atPreflight).map(s => s.state)).toEqual(["pass", "fail", "skipped", "skipped", "skipped"]);
  expect(verificationHeadline(atPreflight).title).toBe("Work order blocked at preflight");

  expect(untestedInstrument(atVerify)?.status).toBe("untested");
  expect(untestedInstrument(atExecute)).toBeUndefined();
});

test("a project with no verified run falls back to its newest run", async () => {
  const blocked = (id: string, created: string) => ({ report: { id, project: "curie", status: "blocked", created_utc: created } });
  const runs = [blocked("new", "2"), blocked("old", "1")];
  expect(currentRun(runs, "curie", null)?.report.id).toBe("new");
  expect(currentRun(runs, "curie", "old")?.report.id).toBe("old");
  expect(currentRun(runs, "linewidth", null)).toBeUndefined();
});

test("browser replay checks the source revision and refuses empty metrics", async () => {
  const source = await readFile("public/evidence/linewidth/20261114T041110Z-b188b519/analysis.py");
  const { source_revision, artifacts, tests } = JSON.parse(
    await readFile("public/evidence/linewidth/20261114T041110Z-b188b519/report.json", "utf8"));
  const digest = await sha256Hex(source);
  expect(() => checkManifest("analysis.py", digest, artifacts)).not.toThrow();
  expect(() => checkSourceRevision(digest, source_revision)).not.toThrow();
  expect(() => checkSourceRevision(digest, "f".repeat(64))).toThrow(/does not match the verified source revision/);
  expect(() => checkSourceRevision(digest, null)).toThrow(/no source revision/);
  expect(() => checkManifest("missing.py", digest, artifacts)).toThrow(/missing from the evidence manifest/);

  const output = Object.fromEntries(tests[0].metrics.map((m: { field: string; expected: number }) => [m.field, m.expected]));
  expect(metricsPass(tests[0], output)).toBe(true);
  expect(metricsPass({ ...tests[0], metrics: [] }, output)).toBe(false);
  expect(metricsPass({ case: "x" }, output)).toBe(false);
  expect(replayScope(1, 4)).toBe("Replayed 1 of 4 reference cases from the factory suite.");
});

test("workspace results and approvals are as strict as the factory", async ({ storage }) => {
  const { runs, specifications } = await createFixtureClient().read("visible-assay");
  const shown = runs.find(run => verifiedResult(run));
  expect(shown).toBeTruthy();
  for (const override of [
    { blockers: ["Calibration expired"] },
    { software: "running" },
    { recipe: "pending" },
  ]) expect(verifiedResult({ ...shown, ...override } as Run)).toBeNull();

  const approved = specifications.find(s => s.approval)!;
  expect(approvalMatches(approved)).toBe(true);
  expect(approvalMatches({ ...approved, approval: { ...approved.approval!, specification_sha256: "0".repeat(64) } })).toBe(false);
  expect(approvalMatches({ ...approved, approval: null })).toBe(false);
});

test("live workspace does not show an approval that pins another revision", async ({ page, storage }) => {
  test.skip(!process.env.NEXT_PUBLIC_WORKSPACE_API_URL, "This build has no workspace service, so live mode is disabled");
  const snapshot = await createFixtureClient().read("visible-assay");
  const spec = snapshot.specifications.find(s => s.approval)!;
  spec.approval = { ...spec.approval!, specification_sha256: "0".repeat(64) };
  await page.route("**/v1/projects/*/workspace?*", route =>
    route.fulfill({ json: { ...snapshot, project_id: "digest-check" } }));
  await page.goto("/workspace/?mode=live&project=digest-check");
  await page.getByRole("navigation", { name: "Workspace views" }).getByRole("button", { name: "Build application" }).click();
  const editor = page.getByRole("region", { name: "Experiment specification" });
  await editor.getByLabel("Saved specification").selectOption(spec.sha256);
  const approval = editor.getByRole("region", { name: "Revision approval" });
  await expect(approval.getByRole("heading")).toHaveText("Approval does not match this revision");
  await expect(approval.getByRole("button", { name: "Submit experiment" })).toBeDisabled();
});

test("live workspace is offered only when a workspace service is configured", async ({ page }) => {
  test.skip(process.env.VERCEL_ENV === "preview", "Preview builds are covered by the source-commit test");
  const requests: string[] = [];
  await page.route("**/v1/**", route => { requests.push(route.request().url()); return route.fulfill({ status: 503 }); });
  await page.goto("/workspace/?mode=live&project=anything");
  const option = page.getByLabel("Data source").locator('option[value="live"]');
  if (process.env.NEXT_PUBLIC_WORKSPACE_API_URL) {
    await expect(option).toBeEnabled();
  } else {
    await expect(option).toBeDisabled();
    await expect(page.getByRole("status").filter({ hasText: "Live workspace is not available yet" })).toBeVisible();
    expect(requests).toEqual([]);
  }
});
