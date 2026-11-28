import { randomUUID } from "node:crypto";
import { expect, test } from "playwright/test";

async function registerSources(request, mode, headers) {
  const labId = "source-lab-" + mode;
  const projectId = "source-project-" + mode;
  const lab = await request.post("/api/context/lab", {headers, data: {
    id: labId, name: "Optics lab " + mode,
    instruments: [{id:"reader", name:"Reader", model:"A1", firmware:"1", notes:"", parameters:[], commands:[]}],
    documents: [{id:"optics", title:"Optics calibration", kind:"note", source:"Notebook", text:"Lab calibration record."}],
  }});
  await expect(lab).toBeOK();
  const project = await request.post("/api/context/experiment", {headers, data: {
    id: projectId, lab_id:labId, title:"Source selection " + mode, goal:"Review reference readings.",
    instrument_ids:["reader"],
    documents:[{id:"reference", title:"Reference list", kind:"note", source:"Project notebook", text:"Project references."}],
  }});
  await expect(project).toBeOK();
  return {projectId, experimentRevision:(await project.json()).revision, labRevision:(await lab.json()).revision};
}

for (const mode of ["untouched", "checked", "none", "reset", "unopened"]) {
  test("the analysis app receives the " + mode + " document selection", async ({page, baseURL}) => {
    const headers = {Origin:baseURL};
    const {projectId, experimentRevision, labRevision} = await registerSources(page.request, mode, headers);
    let route = "/#home/" + encodeURIComponent("lab:" + projectId);
    const followUp = mode === "checked";
    if (followUp) {
      const experiment = await page.request.post("/api/research-experiments", {headers, data: {
        project_id:projectId, request_id:randomUUID(), question:"Do the reference readings agree?",
      }});
      await expect(experiment).toBeOK();
      route += "/" + (await experiment.json()).id;
    }
    await page.goto(route);
    await page.getByLabel("Research objective").fill("Plot optics readings");
    const picker = page.getByRole("button", {name:"Analysis sources"});
    await expect(picker).toBeVisible();
    const submit = page.getByRole("button", {name:followUp ? "Add to experiment" : "Start experiment", exact:true});
    if (mode !== "unopened") {
      if (mode === "untouched") {
        // Hold the inventory read so the keyboard shortcut cannot bypass the loading state.
        let resume;
        const paused = new Promise(resolve => { resume = resolve; });
        await page.route("**/api/research-projects?project=*", async route => {
          await paused;
          await route.continue();
        }, {times:1});
        await picker.click();
        await expect(page.getByText("Loading project documents…")).toBeVisible();
        await expect(submit).toBeDisabled();
        await page.keyboard.press("Control+Enter");
        resume();
      } else {
        await picker.click();
      }
      const lab = page.getByRole("checkbox", {name:"Optics calibration · lab"});
      const project = page.getByRole("checkbox", {name:"Reference list · experiment"});
      await expect(lab).not.toBeChecked();
      await expect(project).toBeChecked();
      if (mode === "checked" || mode === "reset") await lab.check();
      if (mode === "none" || mode === "reset") await project.uncheck();
      if (mode === "reset") {
        await page.getByRole("button", {name:"Use project defaults"}).click();
        await expect(lab).not.toBeChecked();
        await expect(project).toBeChecked();
      }
      if (mode === "checked") await picker.click();
    }
    const saved = page.waitForResponse(response => response.url().endsWith("/api/investigations") && response.request().method() === "POST");
    await submit.click();
    const investigation = await saved;
    expect(investigation.ok()).toBeTruthy();
    const labIds = ["checked", "unopened"].includes(mode) ? ["optics"] : [];
    const experimentIds = mode === "none" ? [] : ["reference"];
    const payload = investigation.request().postDataJSON();
    if (mode === "unopened") expect(payload).not.toHaveProperty("analysis_sources");
    else expect(payload.analysis_sources).toEqual({experiment_id:projectId, experiment_revision:experimentRevision,
      lab_revision:labRevision, lab_document_ids:labIds, experiment_document_ids:experimentIds});

    const app = (await investigation.json()).resources.find(resource => resource.kind === "app");
    const detail = await page.request.get("/api/analysis/apps/" + app.id);
    await expect(detail).toBeOK();
    const [context] = (await detail.json()).contexts;
    expect(context.lab.documents.map(doc => doc.id)).toEqual(labIds);
    expect(context.experiment.documents.map(doc => doc.id)).toEqual(experimentIds);
  });
}
