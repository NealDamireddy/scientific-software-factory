import { test, expect } from "playwright/test";
import { readFile } from "node:fs/promises";

for (const project of ["CW linewidth", "Temperature series"]) {
  test(project + " replays its verified release", async ({ page }) => {
    await page.goto("/epr/");
    await page.getByRole("button", { name: project, exact: true }).click();
    await page.getByRole("button", { name: "Run work order" }).click();
    const run = page.getByRole("button", { name: "Run preflight & replay" });
    const capability = page.getByLabel("Requested capability");
    const supported = await capability.inputValue();
    await capability.selectOption("pulse-acquisition");
    await run.click();
    await expect(page.getByRole("status")).toContainText("Preflight blocked");
    await capability.selectOption(supported);
    await run.click();
    const passed = page.getByRole("status");
    await expect(passed).toContainText("Browser replay passed", { timeout: 65000 });
    await expect(passed).toContainText("matched the verified source revision");
    await expect(passed).toContainText(/Replayed 1 of \d+ reference cases/);
  });
}

test("browser replay refuses source that differs from the verified revision", async ({ page }) => {
  // Serve a different analysis.py. The manifest check fails first, and the
  // replay must stop rather than run the substituted code.
  await page.route("**/evidence/linewidth/*/analysis.py", route =>
    route.fulfill({ body: "print('{}')\n", contentType: "text/x-python" }));
  await page.goto("/epr/");
  await page.getByRole("button", { name: "CW linewidth", exact: true }).click();
  await page.getByRole("button", { name: "Run work order" }).click();
  await page.getByRole("button", { name: "Run preflight & replay" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Replay failed", { timeout: 65000 });
  await expect(status).toContainText("analysis.py failed its integrity check");
});

test("EPR run history and pipeline are drawn from each report's checks", async ({ page }) => {
  await page.goto("/epr/");
  await expect(page.getByRole("note", { name: "Physical instrument caveat" })).toContainText(
    "Physical instrument: untested");
  await page.getByRole("button", { name: "Run history" }).click();
  const history = page.locator(".runList");
  await expect(history).toContainText("Input units failed");
  await expect(history).toContainText("Pulse acquisition failed");
  await expect(history).not.toContainText("Invalid temperature unit");
  await history.getByRole("button", { name: /Input units failed/ }).click();
  await expect(page.getByRole("heading", { name: "Work order blocked at preflight" })).toBeVisible();
  await expect(page.getByText(/^Input units: Required/)).toBeVisible();
  await page.getByRole("button", { name: "Overview" }).click();
  const stages = page.getByRole("list", { name: "Pipeline stages" });
  await expect(stages.getByRole("listitem", { name: "Preflight: fail" })).toContainText("Input units failed");
  await expect(stages.getByRole("listitem", { name: "Generate: not reached" })).toBeVisible();
  await expect(stages.getByRole("listitem", { name: "Verify: not reached" })).toBeVisible();
});

test("B12 presenter exports the committed evidence", async ({ page, request }) => {
  await page.goto("/b12/");
  await expect(page.getByRole("heading", { name: "Vitamin B12 assay" })).toBeVisible();
  const link = page.getByRole("link", { name: "Download run evidence" });
  const response = await request.get(await link.getAttribute("href"));
  expect(response.ok()).toBe(true);
  expect(await response.body()).toEqual(await readFile("public/b12/completed.json"));
  await page.getByRole("link", { name: "EPR workbench" }).click();
  await expect(page.getByRole("button", { name: "Run work order" })).toBeVisible();
});
