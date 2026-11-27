import { readFile } from "node:fs/promises";
import { expect, test } from "playwright/test";

async function checkDownload(page, link, pathname) {
  await expect(link).toHaveAttribute("href", "/evolve/" + pathname);
  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  expect(await download.failure()).toBeNull();
  expect(await readFile(await download.path())).toEqual(await readFile("public/" + pathname));
}

test("reviewer can replay an EPR release and open both EVOLVE archives on the same site", async ({ page, context, baseURL }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
  page.on("response", response => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });
  await page.exposeFunction("recordPolicyViolation", (directive, url) => errors.push(`${directive}: ${url}`));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", event =>
      window.recordPolicyViolation(event.effectiveDirective, event.blockedURI));
  });
  await context.route(/^https?:/, route => {
    const request = route.request();
    if (new URL(request.url()).origin !== baseURL || !["GET", "HEAD"].includes(request.method())) {
      errors.push(`Unexpected request: ${request.method()} ${request.url()}`);
      return route.abort();
    }
    return route.continue();
  });

  const portal = await page.goto("/#orders");
  expect(portal.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByRole("heading", { name: "Work orders", exact: true })).toBeVisible();
  const demos = page.getByRole("link", { name: "EVOLVE demos", exact: true });
  await expect(demos).toHaveCount(1);
  await expect(demos).toHaveAttribute("href", "/evolve/");
  await demos.click();
  await expect(page).toHaveURL(baseURL + "/evolve/");

  await page.getByRole("button", { name: /analysis\.py/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("pre")).toContainText("def ");
  const source = dialog.getByRole("link", { name: "Download file" });
  const sourcePath = await source.getAttribute("href");
  expect(sourcePath).toMatch(/^\/evolve\/evidence\/linewidth\/[\w-]+\/analysis\.py$/);
  await checkDownload(page, source, sourcePath.slice("/evolve/".length));
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Run work order" }).click();
  const [worker] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === "/evolve/replay.mjs"),
    page.getByRole("button", { name: "Run preflight & replay" }).click(),
  ]);
  expect(worker.headers()["content-security-policy"]).toContain("'wasm-unsafe-eval'");
  await expect(page.getByRole("status")).toContainText("Browser replay passed", { timeout: 65000 });
  await dialog.getByRole("button", { name: "Close dialog" }).click();

  await page.getByRole("link", { name: "B12 assay archive" }).click();
  await expect(page).toHaveURL(baseURL + "/evolve/b12/");
  const b12 = await page.reload();
  expect(b12.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByRole("heading", { name: "Vitamin B12 assay" })).toBeVisible();
  await checkDownload(page, page.getByRole("link", { name: "Download run evidence" }), "b12/completed.json");
  await page.locator('a[href="/#b12"], a[href="/#orders"]').first().click();
  await expect(page).toHaveURL(/\/#(?:b12|orders)$/);
  await expect(demos).toBeVisible();

  await demos.click();
  await page.getByRole("link", { name: "Researcher workspace" }).click();
  await expect(page).toHaveURL(/\/evolve\/workspace\/([?].*)?$/);
  await page.goto("/evolve/workspace/?mode=live&project=local-only");
  await page.reload();
  await expect(page.getByText("Isolated fixture data.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /fixture-concentration/ }).click();
  await expect(page.getByRole("region", { name: "Run details" })).toContainText("vial-q17");
  await page.locator('a[href="/#orders"]').click();
  await expect(page.getByRole("heading", { name: "Work orders", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
