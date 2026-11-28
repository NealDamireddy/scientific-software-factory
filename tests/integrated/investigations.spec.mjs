import { expect, test } from "playwright/test";

async function compose(page, objective, {followUp = false} = {}) {
  await page.getByRole("main").getByRole("button", {name: followUp ? "Add work" : "New experiment", exact: true}).click();
  await expect(page.getByRole("heading", {name: followUp ? "What would you like to do next?" : "What are you investigating?"})).toBeVisible();
  await page.getByLabel("Research objective").fill(objective);
  await page.getByRole("button", {name: followUp ? "Add to experiment" : "Start experiment", exact: true}).click();
}

test("a project preserves its hypothesis, experiments, findings and follow-up work", async ({page}) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const projectName = "Archive comparison";
  const initialHypothesis = "Archived mass readings agree across days.";
  const hypothesis = "Archived mass readings agree within each reference group.";
  const question = "Do the archive groups agree?";
  const title = "Archive group agreement";
  const finding = "Two archive groups agreed in the reference comparison.";
  const app = "Plot reference alignment";

  await page.goto("/");
  await page.getByRole("button", {name: "Create project", exact: true}).click();
  await page.getByLabel("Project name").fill(projectName);
  await page.getByLabel("Project hypothesis").fill(initialHypothesis);
  await page.getByRole("dialog").getByRole("button", {name: "Create project"}).click();
  await expect(page.getByRole("heading", {name: projectName})).toBeVisible();
  const projectURL = page.url();
  const projectId = decodeURIComponent(new URL(projectURL).hash.split("/")[1]).slice("lab:".length);
  async function inventory() {
    const res = await page.request.get("/api/research-projects?project=" + encodeURIComponent(projectId));
    expect(res.ok()).toBeTruthy();
    return res.json();
  }
  await expect(page.getByText(initialHypothesis, {exact: true})).toBeVisible();
  await page.getByRole("button", {name: "Edit hypothesis"}).click();
  await page.getByLabel("Project hypothesis").fill(hypothesis);
  await page.getByRole("button", {name: "Save hypothesis"}).click();
  await expect(page.getByText(hypothesis, {exact: true})).toBeVisible();
  await page.reload();
  await expect(page.getByText(hypothesis, {exact: true})).toBeVisible();

  const subject = "Agreement across the archive reference groups";
  await compose(page, subject);
  await page.getByRole("button", {name: "Save experiment question"}).click();
  await page.getByRole("button", {name: "Edit experiment"}).click();
  const experimentURL = page.url();
  const empty = await inventory();
  expect(empty.experiments).toHaveLength(1);
  expect(empty.experiments[0]).toMatchObject({question: subject, requests: [], resources: []});
  await expect(page.getByLabel("Research question")).toHaveValue(subject);
  await page.getByLabel("Research question").fill(question);
  await page.getByLabel("Experiment title").fill(title);
  await page.getByRole("button", {name: "Save experiment"}).click();
  await expect(page.getByRole("heading", {name: title, exact: true})).toBeVisible();
  await page.getByRole("button", {name: "Edit finding"}).click();
  await page.getByLabel("Finding", {exact: true}).fill(finding);
  await page.getByRole("button", {name: "Save finding"}).click();
  await expect(page.getByText(finding, {exact: true})).toBeVisible();

  await compose(page, "Reference alignment", {followUp: true});
  await page.getByRole("button", {name: "Plan a measurement"}).click();
  await expect(page.getByText(/Which method should be followed for “Reference alignment”/)).toBeVisible();
  await expect(page).toHaveURL(experimentURL);
  await compose(page, app, {followUp: true});
  await expect(page.getByText("Queued for an analysis worker.")).toBeVisible();
  await expect(page).toHaveURL(experimentURL);
  await page.reload();
  await expect(page.getByRole("heading", {name: title, exact: true})).toBeVisible();
  await expect(page.getByText(question, {exact: true})).toBeVisible();
  await expect(page.getByText(finding, {exact: true})).toBeVisible();

  const first = (await inventory()).experiments;
  expect(first).toHaveLength(1);
  expect(first[0]).toMatchObject({title, question, finding});
  expect(first[0].requests.map(r => r.objective).sort()).toEqual(["Reference alignment", app].sort());
  const originalApp = first[0].resources.find(r => r.kind === "app");
  expect(originalApp).toBeDefined();

  await page.getByRole("navigation", {name: "Breadcrumb"}).getByRole("button", {name: projectName}).click();
  await expect(page).toHaveURL(projectURL);
  await expect(page.getByRole("button", {name: title, exact: true})).toHaveCount(1);
  await page.getByRole("button", {name: title, exact: true}).click();
  await expect(page.getByRole("heading", {name: title, exact: true})).toBeVisible();
  await expect(page).toHaveURL(experimentURL);
  await page.goto(projectURL);
  await expect(page.getByRole("heading", {name: projectName, exact: true})).toBeVisible();
  await expect(page).toHaveURL(projectURL);
  await compose(page, app);
  const history = page.locator("details").filter({has: page.getByText("Request history (1)", {exact: true})});
  await history.locator("summary").click();
  await expect(history.getByText(/Analysis app · Reused/)).toBeVisible();
  expect(page.url()).not.toBe(experimentURL);
  const siblingURL = page.url();
  const procedure = first[0].resources.find(r => r.kind === "procedure");
  await page.getByText("Use existing project work", {exact: true}).click();
  await page.getByRole("combobox", {name: "Project resource", exact: true}).selectOption(procedure.id);
  await page.getByRole("button", {name: "Attach to experiment"}).click();
  await expect(page.getByRole("button", {name: procedure.title, exact: true})).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(siblingURL);
  await expect(page.getByRole("button", {name: procedure.title, exact: true})).toBeVisible();
  await page.getByRole("navigation", {name: "Breadcrumb"}).getByRole("button", {name: projectName}).click();
  await expect(page.getByRole("heading", {name: projectName, exact: true})).toBeVisible();
  await expect(page.getByRole("button", {name: title, exact: true})).toBeVisible();
  const projects = await inventory();
  expect(projects.hypothesis).toBe(hypothesis);
  expect(projects.experiments).toHaveLength(2);
  const sibling = projects.experiments.find(e => e.id !== first[0].id);
  expect(sibling.resources).toContainEqual(expect.objectContaining({id: procedure.id}));
  expect(sibling.requests[0].resources).toContainEqual(expect.objectContaining({id: originalApp.id, reused: true}));
  expect(projects.resources.filter(r => r.kind === "app")).toHaveLength(1);
  await expect(page.getByRole("button", {name: sibling.title, exact: true})).toBeVisible();
  expect(errors).toEqual([]);
});

test("a new experiment can use data uploaded through the project's analysis intake", async ({page}) => {
  await page.goto("/");
  await page.getByRole("button", {name: "Create project", exact: true}).click();
  await page.getByLabel("Project name").fill("Temperature reference archive");
  await page.getByRole("dialog").getByRole("button", {name:"Create project"}).click();
  await expect(page.getByRole("link", {name: "Upload project readings"})).toBeVisible();
  const question = "Do thermometers agree across the archived readings?";
  await compose(page, question);
  await expect(page.getByText(question, {exact: true}).first()).toBeVisible();
  await expect(page.getByText("No data, procedures or apps attached yet.")).toBeVisible();
  await expect(page).toHaveURL(/#project\/[^/]+\/[^/]+$/);
  const sourceExperiment = page.url();
  await page.getByRole("link", {name: "Upload readings", exact: true}).click();
  await expect(page.getByLabel("What should the analysis report?")).toBeVisible();
  await page.getByLabel("Example dataset").selectOption("temperature");
  await page.getByRole("button", {name: "Load example files"}).click();
  await expect(page.getByLabel("What should the analysis report?")).toHaveValue(/temperatures/);
  await page.getByLabel("Analysis language").selectOption("matlab");
  await page.getByRole("button", {name: "Request analysis", exact: true}).click();
  await expect(page.getByText("matlab", {exact: true})).toBeVisible();
  await expect(page.getByRole("link", {name: "Download original CSV"})).toBeVisible();
  await expect(page.getByRole("link", {name: "Open research project"})).toBeVisible();
  await page.getByRole("link", {name: "Open experiment", exact: true}).click();
  await expect(page).toHaveURL(sourceExperiment);
  await expect(page.getByRole("link", {name: "readings.csv", exact: true})).toBeVisible();
  await page.getByRole("navigation", {name: "Breadcrumb"}).getByRole("button").click();
  await compose(page, "Plot readings.csv");
  const download = page.getByRole("link", {name: "readings.csv", exact: true}).first();
  await expect(download).toBeVisible();
  const source = await page.request.get(await download.getAttribute("href"));
  expect(await source.text()).toContain("voltage_mV");
});

test("a researcher can answer a worker's source question and review the successor", async ({page}) => {
  await page.goto("/#procedures");
  await page.getByRole("button", {name:"Try the procedure review example"}).click();
  await expect(page.getByText("Method source needed", {exact:true})).toBeVisible();
  await page.getByRole("button", {name:"Add example method and redraft"}).click();
  await expect(page.getByText("Read the cited passages in context")).toBeVisible();
  await expect(page.getByText("Previous draft:", {exact:false})).toBeVisible();
  await page.getByRole("button", {name:"Approve submission 1"}).click();
  await page.getByRole("button", {name:"Approve and release"}).click();
  await expect(page.getByText("Released", {exact:true}).first()).toBeVisible();
});
