import { expect, test } from "playwright/test";

test("the researcher composer resolves projects, drafts and apps on the Lab Factory site", async ({page}) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", {name:"What are you investigating?"})).toBeVisible();
  await page.getByRole("button", {name:"Create project", exact:true}).click();
  await page.getByLabel("Project name").fill("Archive comparison");
  await page.getByRole("dialog").getByRole("button", {name:"Create project"}).click();
  await expect(page.getByRole("heading", {name:"Archive comparison"})).toBeVisible();
  await page.getByRole("button", {name:"New investigation", exact:true}).click();
  await page.getByLabel("Research objective").fill("Reference alignment");
  await page.getByLabel("Start investigation").click();
  await expect(page.getByText("What would you like to do in this project?")).toBeVisible();
  await page.getByRole("button", {name:"Plan a measurement"}).click();
  await expect(page.getByText(/needs input/i).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText(/needs input/i).first()).toBeVisible();
  await page.getByRole("button", {name:"New investigation", exact:true}).click();
  await page.getByLabel("Research objective").fill("Plot reference alignment");
  await page.getByLabel("Start investigation").click();
  await expect(page.getByText("Queued for an analysis worker.")).toBeVisible();
  await page.getByRole("link", {name:"Upload project readings"}).click();
  await expect(page.getByLabel("What should the analysis report?")).toBeVisible();
  await expect(page.getByRole("button", {name:"Create project",exact:true})).toBeVisible();
  await page.getByLabel("Example dataset").selectOption("temperature");
  await page.getByRole("button", {name:"Load example files"}).click();
  await expect(page.getByLabel("What should the analysis report?")).toHaveValue(/temperatures/);
  await page.getByLabel("Analysis language").selectOption("matlab");
  await page.getByRole("button", {name:"Request analysis", exact:true}).click();
  await expect(page.getByText("matlab", {exact:true})).toBeVisible();
  await expect(page.getByRole("link", {name:"Download original CSV"})).toBeVisible();
  await page.getByRole("link", {name:"Open research project"}).click();
  await page.getByRole("button", {name:"New investigation", exact:true}).click();
  await page.getByLabel("Research objective").fill("Plot readings.csv");
  await page.getByLabel("Start investigation").click();
  const download = page.getByRole("link", {name:"Dataset · readings.csv"});
  await expect(download.first()).toBeVisible();
  const source = await page.request.get(await download.first().getAttribute("href"));
  expect(await source.text()).toContain("voltage_mV");
  expect(errors).toEqual([]);
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
