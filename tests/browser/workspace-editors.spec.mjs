import { readFileSync } from "node:fs";
import { expect, test } from "playwright/test";

async function openTab(page, tab) {
  await page.getByRole("navigation", { name: "Workspace views" }).getByRole("button", { name: tab }).click();
}

test.beforeEach(async ({ page }) => {
  await page.goto("/workspace/");
});

test("context saves retain immutable lab and project revisions, ownership errors and conflicted input", async ({
  page,
}) => {
  await openTab(page, "Lab & project");
  const lab = page.getByRole("form", { name: "Lab context" });
  const project = page.getByRole("form", { name: "Project context" });
  const name = lab.getByLabel("Lab name");
  const oldName = await name.inputValue();
  for (const label of [
    "Lab ID",
    "Instrument ID",
    "Profile ID",
    "Profile digest (SHA-256)",
    "Approved libraries (one per line)",
    "Operating restrictions (one per line)",
  ]) {
    await expect(lab.getByLabel(label, { exact: true })).not.toHaveValue("");
  }
  await name.fill("Photometry Lab");
  await lab.getByRole("button", { name: "Save lab revision" }).click();
  await expect(lab.getByRole("status")).toHaveText("Saved lab revision 2.");
  await lab.getByLabel("Lab revision").selectOption("1");
  await expect(name).toHaveValue(oldName);
  await name.fill("Concurrent lab edit");
  await lab.getByRole("button", { name: "Save lab revision" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(/revision conflict/i);
  await expect(name).toHaveValue("Concurrent lab edit");

  for (const label of [
    "Project ID",
    "Project lab ID",
    "Scientific objective",
    "Protocol ID",
    "Protocol revision",
    "Concentration unit",
    "Wavelength unit",
    "Path length unit",
    "Analysis method",
    "Validation criteria (one per line)",
  ]) {
    await expect(project.getByLabel(label, { exact: true })).not.toHaveValue("");
  }
  const instrument = project.getByLabel("Project instrument ID");
  const registered = await instrument.inputValue();
  await instrument.fill("outside-lab");
  await project.getByRole("button", { name: "Save project revision" }).click();
  await expect(instrument).toHaveAttribute("aria-invalid", "true");
  await expect(project).toContainText(/instrument owned by this lab/i);
  await expect(instrument).toHaveValue("outside-lab");

  await instrument.fill(registered);
  await project.getByLabel("Scientific objective").fill("Review the concentration series.");
  await project.getByRole("button", { name: "Save project revision" }).click();
  await expect(project.getByRole("status")).toHaveText("Saved project revision 2.");
  await page.reload();
  await openTab(page, "Lab & project");
  await expect(name).toHaveValue("Photometry Lab");
  await expect(project.getByLabel("Project revision")).toHaveValue("2");
  await expect(project.getByLabel("Scientific objective")).toHaveValue("Review the concentration series.");
  await project.getByLabel("Project revision").selectOption("1");
  await expect(project.getByLabel("Scientific objective")).not.toHaveValue(
    "Review the concentration series.",
  );
});

test("concentration draft requires explicit science, exact approval and a new approval after editing", async ({
  page,
}) => {
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", { name: "Experiment specification" });
  const wavelength = editor.getByLabel("Wavelength (nm)", { exact: true });
  const samples = editor.getByLabel("Sample IDs (one per line)");
  const save = editor.getByRole("button", { name: "Save draft revision" });
  const approve = editor.getByRole("button", { name: "Approve revision" });
  const submit = editor.getByRole("button", { name: "Submit experiment" });
  const selection = editor.getByLabel("Saved specification", { exact: true });
  await expect(editor.getByLabel("Experiment type")).toHaveValue("concentration");
  await expect(editor.getByLabel("Replicates")).toHaveValue("3");
  await expect(editor.getByLabel("Path length (mm)")).toHaveValue("10");
  await expect(samples).toHaveValue("");
  await expect(wavelength).toHaveValue("");
  await expect(approve).toHaveCount(0);
  await editor.getByRole("button", { name: "Use project protocol" }).click();
  await expect(wavelength).toHaveValue("");
  await samples.fill("specimen-A");
  await save.click();
  await expect(wavelength).toHaveAttribute("aria-invalid", "true");
  await expect(samples).toHaveValue("specimen-A");
  await page.getByText("Fixture controls", { exact: true }).click();
  await page.getByLabel("Response to next requests").selectOption("unavailable");
  await wavelength.fill("650");
  await save.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(/unavailable/i);
  await openTab(page, "Runs");
  await openTab(page, "Specifications");
  await expect(samples).toHaveValue("specimen-A");
  await expect(wavelength).toHaveValue("650");
  await page.getByLabel("Response to next requests").selectOption("");
  await save.click();
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 1.");
  await expect(approve).toBeDisabled();
  await expect(submit).toBeDisabled();
  await editor.getByLabel("Confirm scientific fields for this revision").check();
  await approve.click();
  await expect(editor.getByRole("status")).toContainText("Approved revision 1.");
  const originalDigest = await selection.inputValue();
  await expect(editor.getByText("Approved digest").locator("+ dd")).toHaveText(originalDigest);
  await expect(editor.getByText("Pinned project").locator("+ dd")).toContainText(
    /visible-assay · revision 1 · [a-f0-9]{64}/,
  );
  await expect(editor.getByText("Pinned lab").locator("+ dd")).toContainText(
    /demo-lab · revision 1 · [a-f0-9]{64}/,
  );
  await samples.fill("specimen-B");
  await expect(submit).toBeDisabled();
  await save.click();
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 2.");
  const newDigest = await selection.inputValue();
  expect(newDigest).not.toBe(originalDigest);
  await expect(submit).toBeDisabled();
  await selection.selectOption(originalDigest);
  await expect(samples).toHaveValue("specimen-A");
  await expect(submit).toBeEnabled();
  await selection.selectOption(newDigest);
  await expect(samples).toHaveValue("specimen-B");
  await expect(editor.getByLabel("Confirm scientific fields for this revision")).not.toBeChecked();
  await editor.getByLabel("Confirm scientific fields for this revision").check();
  await approve.click();
  await expect(editor.getByRole("status")).toContainText("Approved revision 2.");
  await submit.click();
  await expect(editor.getByRole("status")).toContainText("Submitted run fixture-");
  const run = (await editor.getByRole("status").textContent()).match(/fixture-[a-f0-9-]+/)[0];
  await page.reload();
  await expect(page.getByRole("button", { name: new RegExp(run) })).toBeVisible();
  await openTab(page, "Specifications");
  await selection.selectOption(newDigest);
  await expect(samples).toHaveValue("specimen-B");
  await expect(editor.getByText("Approved digest").locator("+ dd")).toHaveText(newDigest);
});

test("time course requires the selected calibration, interval and point count before approval", async ({
  page,
}) => {
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", { name: "Experiment specification" });
  await editor.getByLabel("Experiment type").selectOption("time_course");
  await editor.getByRole("button", { name: "Use project protocol" }).click();
  await editor.getByLabel("Wavelength (nm)", { exact: true }).fill("650");
  const interval = editor.getByLabel("Interval (seconds)");
  const points = editor.getByLabel("Point count");
  await expect(interval).toHaveValue("");
  await expect(points).toHaveValue("");
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByLabel("Frozen calibration")).toHaveAttribute("aria-invalid", "true");
  await editor.getByLabel("Frozen calibration").selectOption({ index: 1 });
  await interval.fill("3601");
  await points.fill("1");
  expect(await interval.evaluate((el) => el.validity.rangeOverflow)).toBe(true);
  expect(await points.evaluate((el) => el.validity.rangeUnderflow)).toBe(true);
  await interval.fill("1");
  await points.fill("100");
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 1.");
  const confirm = editor.getByLabel(/Confirm scientific fields for this revision/);
  await expect(confirm).toHaveAccessibleName(/interval 1 s and 100 points/);
  await confirm.check();
  await editor.getByRole("button", { name: "Approve revision" }).click();
  await expect(editor.getByRole("status")).toContainText("Approved revision 1.");
  await editor.getByRole("button", { name: "Submit experiment" }).click();
  await expect(editor.getByRole("status")).toContainText("Submitted run fixture-");
});

test("live specification handoff surfaces an unsupported type and preserves the draft", async ({ page }) => {
  // Exercise the HTTP boundary with the same public WO-6 context handed to the fixture adapter.
  const context = JSON.parse(
    readFileSync(new URL("../../fixtures/context/demo.json", import.meta.url), "utf8"),
  );
  const id = context.project.project_id;
  const lab = {
    lab_id: context.lab.lab_id,
    project_id: null,
    revision: 7,
    sha256: "a".repeat(64),
    lab_revision: null,
    lab_sha256: null,
    payload: context.lab,
  };
  const project = {
    lab_id: lab.lab_id,
    project_id: id,
    revision: 9,
    sha256: "b".repeat(64),
    lab_revision: lab.revision,
    lab_sha256: lab.sha256,
    payload: context.project,
  };
  const snapshot = {
    project_id: id,
    recorded_at: "2026-11-13T18:00:00Z",
    labs: [lab],
    projects: [project],
    specifications: [],
    calibrations: [],
    runs: [],
  };
  let request;
  await page.route("**/v1/projects/*/workspace?*", (route) => route.fulfill({ json: snapshot }));
  await page.route("**/v1/specifications?*", async (route) => {
    request = route.request().postDataJSON();
    await route.fulfill({
      status: 422,
      json: {
        code: "unsupported_experiment_type",
        fields: {
          experiment_type: "Time course has no supported verification contract on this service.",
        },
      },
    });
  });
  await page.goto("/workspace/?mode=live&project=" + id);
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", { name: "Experiment specification" });
  await editor.getByLabel("Experiment type").selectOption("time_course");
  await editor.getByRole("button", { name: "Use project protocol" }).click();
  await editor.getByLabel("Sample IDs (one per line)").fill("retained-vial");
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByLabel("Experiment type")).toHaveAccessibleDescription(
    /no supported verification contract/,
  );
  await expect(editor.getByLabel("Sample IDs (one per line)")).toHaveValue("retained-vial");
  expect(request.expected_revision).toBe(0);
  expect(request.payload.project).toEqual({
    project_id: id,
    lab_id: lab.lab_id,
    revision: 9,
    sha256: project.sha256,
  });
  expect(request.payload.lab).toEqual({
    project_id: null,
    lab_id: lab.lab_id,
    revision: 7,
    sha256: lab.sha256,
  });
  expect(request.payload.settings.wavelength_nm).toBeNull();
});

test("fixture rejects sample collisions, incomplete standards and unsupported protocol units", async ({page}) => {
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", {name:"Experiment specification"});
  const save = editor.getByRole("button", {name:"Save draft revision"});
  const samples = editor.getByLabel("Sample IDs (one per line)");
  const alert = page.getByRole("main").getByRole("alert");
  await editor.getByRole("button", {name:"Use project protocol"}).click();
  await editor.getByLabel("Wavelength (nm)").fill("650");
  for (const ids of ["vial-q17\nvial-q17", "std-1"]) {
    await samples.fill(ids);
    await save.click();
    await expect(alert).toContainText(/sample_ids|standards/);
    await expect(editor.getByRole("button", {name:"Approve revision"})).toHaveCount(0);
    await expect(samples).toHaveValue(ids);
  }
  await samples.fill("vial-q17");
  await editor.getByRole("button", {name:"Add standard"}).click();
  await save.click();
  await expect(alert).toContainText("standards");
  await editor.getByRole("button", {name:"Remove standard 4"}).click();
  await openTab(page, "Lab & project");
  const project = page.getByRole("form", {name:"Project context"});
  await project.getByLabel("Concentration unit", {exact:true}).fill("mol/L");
  await project.getByRole("button", {name:"Save project revision"}).click();
  await expect(project.getByRole("status")).toContainText("Saved project revision 2");
  await openTab(page, "Specifications");
  await editor.getByLabel("Specification project revision").selectOption("2");
  await editor.getByRole("button", {name:"Use project protocol"}).click();
  await save.click();
  await expect(alert).toContainText("mg/L");
  await expect(editor.getByRole("button", {name:"Approve revision"})).toHaveCount(0);
});
