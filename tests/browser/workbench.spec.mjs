import { test, expect } from "playwright/test";
import { readFile } from "node:fs/promises";

for (const project of ["CW linewidth", "Temperature series"]) {
  test(project + " replays its verified release", async ({ page }) => {
    await page.goto("/");
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
    await expect(page.getByRole("status")).toContainText("Browser replay passed", { timeout: 65000 });
  });
}

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
