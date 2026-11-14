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
  const incompleteDigest = await selection.inputValue();
  await page.reload();
  await openTab(page, "Specifications");
  await selection.selectOption(incompleteDigest);
  await expect(wavelength).toHaveAttribute("aria-invalid", "true");
  await expect(samples).toHaveValue("specimen-A");
  await expect(approve).toBeDisabled();
  await expect(submit).toBeDisabled();
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
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 2.");
  await expect(approve).toBeDisabled();
  await expect(submit).toBeDisabled();
  await editor.getByLabel("Confirm scientific fields for this revision").check();
  await approve.click();
  await expect(editor.getByRole("status")).toContainText("Approved revision 2.");
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
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 3.");
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
  await expect(editor.getByRole("status")).toContainText("Approved revision 3.");
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
  await interval.fill("8");
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByLabel("Frozen calibration")).toHaveAttribute("aria-invalid", "true");
  await expect(interval).toHaveValue("8");
  await expect(points).toHaveValue("");
  await expect(editor.getByRole("button", { name: "Approve revision" })).toBeDisabled();
  await editor.getByLabel("Frozen calibration").selectOption({ index: 1 });
  await interval.fill("3601");
  await points.fill("1");
  expect(await interval.evaluate((el) => el.validity.rangeOverflow)).toBe(true);
  expect(await points.evaluate((el) => el.validity.rangeUnderflow)).toBe(true);
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByRole("status")).toHaveText("Saved unapproved draft revision 2.");
  const saved = editor.getByLabel("Saved specification", {exact: true});
  const digest = await saved.inputValue();
  await page.reload();
  await openTab(page, "Specifications");
  await saved.selectOption(digest);
  await expect(interval).toHaveValue("3601");
  await expect(points).toHaveValue("1");
  await expect(interval).toHaveAccessibleDescription(/1–3600/);
  await expect(points).toHaveAccessibleDescription(/2–100/);
  await expect(editor.getByRole("button", { name: "Approve revision" })).toBeDisabled();
  await interval.fill("1");
  await points.fill("100");
  await editor.getByRole("button", { name: "Save draft revision" }).click();
  await expect(editor.getByRole("status")).toContainText("Saved unapproved draft revision 3.");
  const confirm = editor.getByLabel(/Confirm scientific fields for this revision/);
  await expect(confirm).toHaveAccessibleName(/interval 1 s and 100 points/);
  await confirm.check();
  await editor.getByRole("button", { name: "Approve revision" }).click();
  await expect(editor.getByRole("status")).toContainText("Approved revision 3.");
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
  const issues = editor.getByRole("region", {name:"Unresolved scientific fields"});
  await editor.getByRole("button", {name:"Use project protocol"}).click();
  await editor.getByLabel("Wavelength (nm)").fill("650");
  for (const ids of ["vial-q17\nvial-q17", "std-1"]) {
    await samples.fill(ids);
    await save.click();
    await expect(issues).toContainText(/sample_ids|standards/);
    await expect(editor.getByRole("button", {name:"Approve revision"})).toBeDisabled();
    await expect(samples).toHaveValue(ids);
  }
  await samples.fill("vial-q17");
  await editor.getByRole("button", {name:"Add standard"}).click();
  await save.click();
  await expect(issues).toContainText("standards");
  await editor.getByRole("button", {name:"Remove standard 4"}).click();
  await openTab(page, "Lab & project");
  const project = page.getByRole("form", {name:"Project context"});
  await project.getByLabel("Concentration unit", {exact:true}).fill("mol/L");
  await project.getByRole("button", {name:"Save project revision"}).click();
  await expect(project.getByRole("status")).toContainText("Saved project revision 2");
  await openTab(page, "Specifications");
  await editor.getByLabel("Saved specification", {exact:true}).selectOption({ label: "New specification" });
  await editor.getByLabel("Specification project revision").selectOption("2");
  await editor.getByRole("button", {name:"Use project protocol"}).click();
  await save.click();
  await expect(issues).toContainText("mg/L");
  await expect(editor.getByRole("button", {name:"Approve revision"})).toBeDisabled();
});

test("protected specification fields follow the pinned protocol and experiment type", async ({page}) => {
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", {name:"Experiment specification"});
  const outputs = editor.getByLabel("Expected outputs (one per line)");
  const criteria = editor.getByLabel("Specification validation criteria (one per line)");
  const units = editor.getByLabel("Result concentration unit");
  for (const control of [outputs, criteria, units]) await expect(control).not.toBeEditable();
  await expect(criteria).toHaveValue(/positive calibration slope/);
  await expect(units).toHaveValue("mg/L");
  await expect(outputs).not.toHaveValue(/timestamp/);
  await editor.getByLabel("Experiment type").selectOption("time_course");
  await expect(outputs).toHaveValue(/timestamp$/);
  await openTab(page, "Lab & project");
  const project = page.getByRole("form", {name:"Project context"});
  await project.getByLabel("Validation criteria (one per line)").fill("Revised protocol threshold");
  await project.getByRole("button", {name:"Save project revision"}).click();
  await expect(project.getByRole("status")).toContainText("Saved project revision 2");
  await openTab(page, "Specifications");
  await expect(criteria).toHaveValue(/positive calibration slope/);
  await editor.getByLabel("Specification project revision").selectOption("2");
  await expect(criteria).toHaveValue("Revised protocol threshold");
});

test("saved edits retain historical context and new specifications can choose either revision", async ({ page }) => {
  await openTab(page, "Lab & project");
  const lab = page.getByRole("form", { name: "Lab context" });
  await lab.getByLabel("Lab name").fill("Revised assay lab");
  await lab.getByRole("button", { name: "Save lab revision" }).click();
  await expect(lab.getByRole("status")).toHaveText("Saved lab revision 2.");
  const project = page.getByRole("form", { name: "Project context" });
  // An unchanged project payload repeats its digest while the saved revision pins lab 2.
  await project.getByRole("button", { name: "Save project revision" }).click();
  await expect(project.getByRole("status")).toHaveText("Saved project revision 2.");

  await openTab(page, "Specifications");
  const editor = page.getByRole("region", { name: "Experiment specification" });
  const saved = editor.getByLabel("Saved specification", { exact: true });
  const revision = editor.getByLabel("Specification project revision");
  const pinned = (label) => editor.getByText(label, { exact: true }).locator("+ dd");
  const save = editor.getByRole("button", { name: "Save draft revision" });
  const submit = editor.getByRole("button", { name: "Submit experiment" });
  await saved.selectOption({ label: "spec-concentration · revision 1 · approved" });
  const original = await saved.inputValue();
  const oldLab = await pinned("Pinned lab").innerText();
  const oldProject = await pinned("Pinned project").innerText();
  const projectDigest = await pinned("Pinned project").locator("code").innerText();
  await expect(revision).not.toBeEditable();
  await editor.getByLabel("Sample IDs (one per line)").fill("historical-specimen");
  await save.click();
  await expect(editor.getByRole("status")).toHaveText("Saved unapproved draft revision 2.");
  await expect(saved.locator("option:checked")).toHaveText("spec-concentration · revision 2 · draft");
  await expect(pinned("Pinned lab")).toHaveText(oldLab);
  await expect(pinned("Pinned project")).toHaveText(oldProject);
  const edited = await saved.inputValue();
  expect(edited).not.toBe(original);
  await expect(submit).toBeDisabled();
  await expect(editor.getByLabel("Confirm scientific fields for this revision")).not.toBeChecked();
  await editor.getByLabel("Confirm scientific fields for this revision").check();
  await editor.getByRole("button", { name: "Approve revision" }).click();
  await expect(pinned("Approved digest")).toHaveText(edited);
  await saved.selectOption(original);
  await expect(pinned("Approved digest")).toHaveText(original);
  await expect(editor.getByLabel("Sample IDs (one per line)")).not.toHaveValue("historical-specimen");

  const ids = new Set(["spec-concentration"]);
  for (const contextRevision of ["1", "2"]) {
    await saved.selectOption({ label: "New specification" });
    await revision.selectOption(contextRevision);
    await editor.getByRole("button", { name: "Use project protocol" }).click();
    await editor.getByLabel("Wavelength (nm)", { exact: true }).fill("650");
    await save.click();
    await expect(editor.getByRole("status")).toHaveText("Saved unapproved draft revision 1.");
    const id = (await saved.locator("option:checked").innerText()).split(" · ")[0];
    expect(ids.has(id)).toBe(false);
    ids.add(id);
    await expect(pinned("Pinned project")).toContainText("revision " + contextRevision + " ·");
    await expect(pinned("Pinned project").locator("code")).toHaveText(projectDigest);
    await expect(pinned("Pinned lab")).toContainText("revision " + contextRevision + " ·");
    await expect(submit).toBeDisabled();
  }
});

test("duplicate instrument shows the correction at the edited ID and preserves all inputs", async ({ page }) => {
  await openTab(page, "Lab & project");
  const lab = page.getByRole("form", {name: "Lab context"});
  await lab.getByLabel("Lab name").fill("Lab with secondary instrument");
  await lab.getByRole("button", {name: "Add instrument"}).click();
  const first = lab.getByRole("group", {name: "Instrument 1"});
  const second = lab.getByRole("group", {name: "Instrument 2"});
  for (const label of ["Instrument ID", "Profile ID", "Profile digest (SHA-256)"]) {
    await second.getByLabel(label, {exact:true}).fill(await first.getByLabel(label, {exact:true}).inputValue());
  }
  const id = second.getByLabel("Instrument ID", {exact:true});
  const save = lab.getByRole("button", {name: "Save lab revision"});
  await save.click();
  await expect(id).toHaveAccessibleDescription(/duplicate instrument ID/i);
  await expect(id).toHaveValue(await first.getByLabel("Instrument ID", {exact:true}).inputValue());
  await expect(lab.getByLabel("Lab name")).toHaveValue("Lab with secondary instrument");
  await expect(lab.getByLabel("Lab revision")).toHaveValue("1");
  await id.fill("invalid id");
  await save.click();
  await expect(id).toHaveAccessibleDescription(/instrument ID containing/i);
  await id.fill("secondary-uvvis");
  await save.click();
  await expect(lab.getByRole("status")).toHaveText("Saved lab revision 2.");
});

test("a concentration edit preserves the selected optional frozen calibration", async ({page}) => {
  await openTab(page, "Specifications");
  const editor = page.getByRole("region", {name:"Experiment specification"});
  const calibration = editor.getByLabel("Frozen calibration (optional)");
  const save = editor.getByRole("button", {name:"Save draft revision"});
  await editor.getByRole("button", {name:"Use project protocol"}).click();
  await editor.getByLabel("Wavelength (nm)").fill("650");
  await calibration.selectOption({index:1});
  const digest = await calibration.inputValue();
  await save.click();
  await expect(editor.getByRole("status")).toHaveText("Saved unapproved draft revision 1.");
  await editor.getByLabel("Sample IDs (one per line)").fill("vial-after-edit");
  await save.click();
  await expect(editor.getByRole("status")).toHaveText("Saved unapproved draft revision 2.");
  await expect(calibration).toHaveValue(digest);
  await editor.getByLabel("Confirm scientific fields for this revision").check();
  await editor.getByRole("button", {name:"Approve revision"}).click();
  await expect(editor.getByRole("status")).toHaveText("Approved revision 2.");
});
