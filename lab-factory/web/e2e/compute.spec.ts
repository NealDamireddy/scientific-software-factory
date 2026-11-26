import { readFile } from "node:fs/promises";

import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { COOMASSIE } from "./helpers.ts";

// Pyodide loads in the worker on the first run, so the first computed result gets a long wait.
const FIRST_RUN = { timeout: 80_000 };
const RATE = /^Rate constant 0\.008[3-7]\d* per s$/;

function panel(page: Page) {
  return page.getByRole("region", { name: "Outputs" });
}

async function openTab(page: Page, name: string) {
  const tab = panel(page).getByRole("tab", { name, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return panel(page).getByRole("tabpanel", { name, exact: true });
}

function csv(name: string, text: string) {
  return { name, mimeType: "text/csv", buffer: Buffer.from(text) };
}

// Readings never leave the browser: every request the page makes stays on this origin.
let requests: string[] = [];
test.beforeEach(async ({ page }) => {
  requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto(COOMASSIE);
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
});

test.afterEach(async ({ baseURL }) => {
  const foreign = requests.filter((url) => !url.startsWith(`${baseURL}/`) && !url.startsWith("data:") && !url.startsWith("blob:"));
  expect(foreign).toEqual([]);
});

test("the Analysis app tab runs its 3 reference cases in the browser and all pass", async ({ page }) => {
  const body = await openTab(page, "Analysis app");
  await expect(body.getByRole("heading", { level: 2, name: "Analysis app" })).toBeVisible();
  await expect(body.getByText("Turns absorbance over time into a rate constant and half-life.")).toBeVisible();
  await expect(body.getByRole("region", { name: "Analysis app code" })).toContainText("def analyze(readings):");
  const table = body.getByRole("table", { name: "Reference cases" });
  await expect(table.getByRole("columnheader")).toHaveText(["Case", "Expected", "Found", "Result"]);
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.filter({ hasText: "Passed" })).toHaveCount(3, FIRST_RUN);
  await expect(rows.nth(0).getByRole("rowheader")).toHaveText("Clean decay");
  await expect(rows.nth(0).getByRole("cell").nth(0)).toHaveText("0.01 per s");
  await expect(rows.nth(0).getByRole("cell").nth(1)).toHaveText(/^0\.0(09[5-9]|10[0-5])\d? per s$/);
  await expect(rows.nth(2).getByRole("cell").nth(0)).toHaveText("no decay");
  await expect(rows.nth(2).getByRole("cell").nth(1)).toHaveText("no decay");
  await expect(rows.filter({ hasText: "Failed" })).toHaveCount(0);
  await expect(body.getByText("Running in your browser…")).toHaveCount(0);
  await expect(body.getByRole("status").filter({ hasText: "Reference cases" })).toHaveText("Reference cases done: 3 of 3 passed.");
});

test("Copy code puts the analysis app's code on the clipboard", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const body = await openTab(page, "Analysis app");
  await body.getByRole("button", { name: "Copy code" }).click();
  await expect(body.getByRole("status").filter({ hasText: "Copied" })).toHaveCount(1);
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("def analyze(readings):");
});

test("the sample readings download, upload back and give the rate, half-life and a 61-point plot", async ({ page }) => {
  const body = await openTab(page, "Results");
  await expect(body.getByRole("heading", { level: 2, name: "Results" })).toBeVisible();
  await expect(body.getByText("Readings stay in your browser. The analysis runs on this computer.")).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    body.getByRole("button", { name: "Download sample readings" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("coomassie-readings.csv");
  const text = await readFile(await download.path(), "utf8");
  expect(text.split("\n")[0]).toBe("time_s,absorbance");
  expect(text.trim().split("\n")).toHaveLength(62);

  await body.getByLabel("Upload readings (CSV)").setInputFiles(csv("coomassie-readings.csv", text));
  const results = body.getByRole("list", { name: "Analysis results" });
  await expect(results.getByText(RATE)).toBeVisible(FIRST_RUN);
  await expect(results.getByText(/^Half-life \d+(\.\d+)? s$/)).toBeVisible();
  await expect(results.getByText(/^Fit error \(RMS\) 0\.\d+ AU$/)).toBeVisible();
  await expect(body.getByText("Analyzed coomassie-readings.csv", { exact: true })).toBeVisible();
  await expect(body.getByRole("status")).toHaveText(/^Analyzed coomassie-readings\.csv\. Rate constant 0\.008[3-7]\d* per s\.$/);

  const plot = body.getByRole("img", { name: "Readings and fit. Readings: 61 points. Fit: line." });
  await expect(plot).toBeVisible();
  const legend = body.getByRole("list", { name: "Legend" });
  await expect(legend.getByRole("listitem")).toHaveText(["Readings", "Fit"]);
  const show = body.getByRole("button", { name: "Show data" });
  await expect(show).toHaveAttribute("aria-expanded", "false");
  await show.click();
  await expect(show).toHaveAttribute("aria-expanded", "true");
  const data = body.getByRole("table", { name: "Readings and fit" });
  await expect(data.locator("tbody tr")).toHaveCount(61);
  await expect(data.getByRole("columnheader")).toHaveText(["Time (s)", "Readings", "Fit"]);
  // The fit is drawn on its own dense, sorted grid; the table keeps one row per reading.
  const fit = await plot.locator("polyline").getAttribute("points");
  const xs = (fit ?? "").trim().split(" ").map((p) => Number(p.split(",")[0]));
  expect(xs).toHaveLength(200);
  expect(xs.every((v, i) => i === 0 || v > xs[i - 1])).toBe(true);
  await expect(body.getByText(/^Showing /)).toHaveCount(0);

  // A bad file afterwards replaces the result with the error.
  await body.getByLabel("Upload readings (CSV)").setInputFiles(csv("bad.csv", "time_s,absorbance\n0,abc\n10,0.7\n"));
  await expect(body.getByRole("alert")).toHaveText("Row 2 has a value that isn't a number.");
  await expect(results).toHaveCount(0);
  await expect(plot).toHaveCount(0);

  // The same bad file again is announced again: the alert is a new node, not the old one left alone.
  const first = await body.getByRole("alert").elementHandle();
  await body.getByLabel("Upload readings (CSV)").setInputFiles(csv("bad.csv", "time_s,absorbance\n0,abc\n10,0.7\n"));
  await expect.poll(() => first?.evaluate((node) => node.isConnected)).toBe(false);
  await expect(body.getByRole("alert")).toHaveText("Row 2 has a value that isn't a number.");

  // The same good file again runs again.
  await body.getByLabel("Upload readings (CSV)").setInputFiles(csv("coomassie-readings.csv", text));
  await expect(body.getByRole("list", { name: "Analysis results" }).getByText(RATE)).toBeVisible(FIRST_RUN);
  await expect(body.getByRole("alert")).toHaveCount(0);
});

test("readings from the instrument data folder are analyzed without an upload", async ({ page }) => {
  const body = await openTab(page, "Results");
  const folder = body.getByRole("region", { name: "From your instrument data folder" });
  await expect(folder.getByText("Sample connection", { exact: true })).toBeVisible();
  await folder.getByRole("button", { name: "Analyze coomassie-run-1.csv" }).click();
  await expect(body.getByRole("list", { name: "Analysis results" }).getByText(RATE)).toBeVisible(FIRST_RUN);
  await expect(body.getByText("Analyzed coomassie-run-1.csv", { exact: true })).toBeVisible();
});

test("malformed readings get the exact error, never a result", async ({ page }) => {
  const body = await openTab(page, "Results");
  const input = body.getByLabel("Upload readings (CSV)");
  const alert = body.getByRole("alert");

  await input.setInputFiles(csv("text.csv", "time_s,absorbance\n0,abc\n10,0.7\n20,0.6\n30,0.5\n40,0.4\n"));
  await expect(alert).toHaveText("Row 2 has a value that isn't a number.");

  await input.setInputFiles(csv("columns.csv", "time,absorbance\n0,0.8\n10,0.7\n20,0.6\n30,0.5\n40,0.4\n"));
  await expect(alert).toHaveText("The file needs a time_s column and an absorbance column.");

  await input.setInputFiles(csv("short.csv", "time_s,absorbance\n0,0.8\n10,0.7\n20,0.6\n30,0.5\n"));
  await expect(alert).toHaveText("The analysis needs at least 5 readings.");
  await expect(body.getByRole("list", { name: "Analysis results" })).toHaveCount(0);
  await expect(body.getByRole("img")).toHaveCount(0);
});

test("readings that share a time and come out of order each keep their row, and equal times get a plain error", async ({ page }) => {
  const body = await openTab(page, "Results");
  const input = body.getByLabel("Upload readings (CSV)");
  await input.setInputFiles(csv("shuffled.csv", "time_s,absorbance\n300,0.11\n0,0.8\n100,0.37\n100,0.36\n600,0.05\n200,0.19\n0,0.79\n"));
  await expect(body.getByRole("list", { name: "Analysis results" })).toBeVisible(FIRST_RUN);
  await body.getByRole("button", { name: "Show data" }).click();
  const rows = body.getByRole("table", { name: "Readings and fit" }).locator("tbody tr");
  await expect(rows).toHaveCount(7);
  await expect(rows.getByRole("rowheader")).toHaveText(["300", "0", "100", "100", "600", "200", "0"]);

  await input.setInputFiles(csv("same.csv", "time_s,absorbance\n5,0.8\n5,0.7\n5,0.6\n5,0.5\n5,0.4\n"));
  await expect(body.getByRole("alert")).toHaveText("The time_s values are all the same. The analysis needs readings at different times.");
});

test("20,000 readings are analyzed, drawn as a sample and listed in part, and the page keeps working", async ({ page }) => {
  const body = await openTab(page, "Results");
  const lines = ["time_s,absorbance"];
  for (let i = 0; i < 20_000; i += 1) {
    const t = i * 0.03;
    lines.push(`${t.toFixed(2)},${(0.05 + 0.75 * Math.exp(-0.0085 * t)).toFixed(5)}`);
  }
  await body.getByLabel("Upload readings (CSV)").setInputFiles(csv("long-run.csv", `${lines.join("\n")}\n`));
  await expect(body.getByRole("list", { name: "Analysis results" }).getByText(/^Rate constant 0\.008[4-6]\d* per s$/)).toBeVisible(FIRST_RUN);
  await expect(page.getByRole("list", { name: "Conversation" })).toBeVisible();
  await expect(body.getByText("Showing 2,000 of 20,000 readings. The analysis used all of them.", { exact: true })).toBeVisible();
  await expect(body.getByRole("img", { name: /^Readings and fit\./ }).locator("circle")).toHaveCount(2000);
  await body.getByRole("button", { name: "Show data" }).click();
  await expect(body.getByText("Showing the first 2,000 of 20,000 rows.", { exact: true })).toBeVisible();
  await expect(body.getByRole("table", { name: "Readings and fit" }).locator("tbody tr")).toHaveCount(2000);
});

test("the simulation runs and plots three fading curves", async ({ page }) => {
  const body = await openTab(page, "Simulation");
  await expect(body.getByRole("heading", { level: 2, name: "Extra: simulation" })).toBeVisible();
  await expect(body.getByText("Fading curves for three amounts of reducing agent").first()).toBeVisible();
  await expect(body.getByText("Sample content", { exact: true })).toBeVisible();
  await expect(body.getByRole("region", { name: "Simulation code" })).toContainText("def simulate(");
  await body.getByRole("button", { name: "Run simulation" }).click();
  const legend = body.getByRole("list", { name: "Legend" });
  await expect(legend.getByRole("listitem")).toHaveText(["0.5 mM", "1.0 mM", "2.0 mM"], FIRST_RUN);
  await expect(body.getByRole("img", { name: /^Fading curves for three amounts of reducing agent\. 0\.5 mM: line\./ })).toBeVisible();
  await expect(body.getByRole("status").filter({ hasText: "Simulation" })).toHaveText("Simulation done.");
  await body.getByRole("button", { name: "Show data" }).click();
  await expect(body.getByRole("table").locator("tbody tr")).toHaveCount(61);
});

test("when the runtime can't load, the exact error shows, the page stays usable and a retry works", async ({ page }) => {
  // A runtime file that fails to download makes Pyodide's load reject. (An aborted pyodide.asm.wasm
  // instead leaves the load hanging, which ends in the 60 s timeout copy.)
  const RUNTIME_FILE = "**/runtime/pyodide-lock.json";
  await page.route(RUNTIME_FILE, (route) => route.abort());
  const body = await openTab(page, "Analysis app");
  const alert = body.getByRole("alert");
  await expect(alert).toHaveText(/^The analysis runtime couldn't load: .+/, FIRST_RUN);
  await expect(body.getByText("Running in your browser…")).toHaveCount(0);

  const procedure = await openTab(page, "Procedure");
  await expect(procedure.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();

  await page.unroute(RUNTIME_FILE);
  const again = await openTab(page, "Analysis app");
  await again.getByRole("button", { name: "Try again" }).click();
  await expect(again.locator("tbody tr").filter({ hasText: "Passed" })).toHaveCount(3, FIRST_RUN);
  await expect(again.getByRole("alert")).toHaveCount(0);
});
