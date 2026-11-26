import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, attachProtocol } from "./helpers.ts";

const EARLIER = "You're viewing an earlier submission.";

function tabBody(page: Page, name: string) {
  return page.getByRole("region", { name: "Outputs" }).getByRole("tabpanel", { name });
}

async function openTab(page: Page, name: string) {
  const tab = page.getByRole("region", { name: "Outputs" }).getByRole("tab", { name });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return tabBody(page, name);
}

async function optionTexts(body: ReturnType<typeof tabBody>, label: string): Promise<string[]> {
  return body.getByLabel(label, { exact: true }).locator("option").allTextContents();
}

test.describe("Coomassie after the protocol is attached", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(COOMASSIE);
    await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
    await attachProtocol(page);
    const body = tabBody(page, "Procedure");
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
  });

  test("the picker lists both orders' submissions, newest first", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const picker = body.getByLabel("Submission", { exact: true });
    await expect(picker).toBeVisible();
    await expect.poll(() => optionTexts(body, "Submission")).toEqual([
      "WO-2 submission 1, all checks passed",
      "WO-1 submission 1, 1 check failed",
    ]);
    await expect(body.getByText(EARLIER)).toHaveCount(0);
  });

  test("choosing WO-1 shows its submission, status and failure, and Back to the latest returns", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    await body.getByLabel("Submission", { exact: true }).selectOption({ label: "WO-1 submission 1, 1 check failed" });
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();
    await expect(body.getByText("Being revised", { exact: true })).toBeVisible();
    await expect(body.getByText(EARLIER, { exact: true })).toBeVisible();
    await expect(body.getByText("step 4: citations: no citation", { exact: true })).toBeVisible();

    await body.getByRole("button", { name: "Back to the latest" }).click();
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
    await expect(body.getByLabel("Submission", { exact: true })).toBeFocused();
    await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
    await expect(body.getByText(EARLIER)).toHaveCount(0);
    await expect(body.getByLabel("Submission", { exact: true })).toHaveValue("WO-2#1");
    await expect(body.getByText("step 4: citations: no citation")).toHaveCount(0);
  });

  test("comparing WO-2 with WO-1 shows one changed step and four unchanged", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const compare = body.getByRole("button", { name: "Compare" });
    await expect(compare).toBeEnabled();
    await compare.click();
    await expect(compare).toHaveAttribute("aria-expanded", "true");
    const controls = await compare.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    await expect(page.locator(`[id="${controls}"]`)).toHaveAccessibleName("Comparing WO-2 submission 1");
    const withSelect = body.getByLabel("Compare with", { exact: true });
    await expect.poll(() => optionTexts(body, "Compare with")).toEqual(["WO-1 submission 1, 1 check failed"]);
    await expect(withSelect).toHaveValue("WO-1#1");
    const rows = body.getByRole("list", { name: "Changes" }).getByRole("listitem");
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: "Changed: " })).toHaveCount(1);
    await expect(rows.nth(0)).toContainText("Changed: citations");
    await expect(rows.nth(0)).toContainText("Step 4");
    await expect(rows.nth(1)).toHaveText("4 unchanged steps");
    await expect(rows.filter({ hasText: /^(Added|Removed)/ })).toHaveCount(0);

    await body.getByRole("button", { name: "Close comparison" }).click();
    await expect(body.getByRole("list", { name: "Changes" })).toHaveCount(0);
    await expect(compare).toBeFocused();
  });

  test("Built from lists the pins, the artifact and the attached document", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
    await built.getByText("Built from", { exact: true }).click();
    await expect(built).toHaveAttribute("open", "");
    await expect(built.getByText("Experiment revision 2", { exact: true })).toBeVisible();
    await expect(built.getByText("Lab revision 1", { exact: true })).toBeVisible();
    await expect(built.getByText("Project revision 1", { exact: true })).toBeVisible();
    await expect(built.getByText("Skill How we write procedures revision 1", { exact: true })).toBeVisible();
    await expect(built.getByText("Artifact", { exact: true })).toBeVisible();
    await expect(built.getByText(/^[0-9a-f]{12}$/).first()).toBeVisible();
    await expect(built.getByRole("button", { name: "Copy Experiment revision 2 digest" })).toBeVisible();
    await expect(built.getByRole("button", { name: "Copy artifact digest" })).toBeVisible();

    const source = built.getByRole("link", { name: "reduction-protocol.txt" });
    await source.click();
    const drawer = page.getByRole("complementary", { name: "Document" });
    await expect(drawer.getByRole("heading", { level: 2, name: "reduction-protocol.txt" })).toBeVisible();
    await expect(drawer).toContainText("Add the reducing agent dropwise.");
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toHaveCount(0);
    await expect(source).toBeFocused();
  });

  test("Copy puts the line's full digest on the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const body = tabBody(page, "Procedure");
    const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
    await built.getByText("Built from", { exact: true }).click();
    const line = built.getByRole("listitem").filter({ hasText: "Experiment revision 2" });
    const shown = (await line.locator("code").textContent()) ?? "";
    expect(shown).toMatch(/^[0-9a-f]{12}$/);
    await line.getByRole("button", { name: "Copy Experiment revision 2 digest" }).click();
    await expect(line.getByRole("status")).toHaveText("Copied");
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toMatch(/^[0-9a-f]{64}$/);
    expect(copied.startsWith(shown)).toBe(true);
  });

  test("when copying fails, the full digest is offered on that line to copy by hand", async ({ page }) => {
    await page.evaluate(() => {
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")) } });
    });
    const body = tabBody(page, "Procedure");
    const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
    await built.getByText("Built from", { exact: true }).click();
    await built.getByRole("button", { name: "Copy Experiment revision 2 digest" }).click();
    const field = built.getByRole("textbox", { name: "Experiment revision 2 digest" });
    await expect(field).toHaveValue(/^[0-9a-f]{64}$/);
    await expect(field).toHaveAttribute("readonly", "");
    await expect(field).toBeFocused();
    const line = built.getByRole("listitem").filter({ hasText: "Experiment revision 2" });
    await expect(line.getByRole("alert")).toHaveText("Couldn't copy. Copy the digest below.");

    await built.getByRole("button", { name: "Copy artifact digest" }).click();
    await expect(built.getByRole("textbox", { name: "Artifact digest" })).toHaveValue(/^[0-9a-f]{64}$/);
    await expect(built.getByRole("alert")).toHaveCount(1);
    await expect(built.getByRole("textbox")).toHaveCount(1);
  });

  test("Built from stays open while switching submissions", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
    await built.getByText("Built from", { exact: true }).click();
    await expect(built).toHaveAttribute("open", "");
    await body.getByLabel("Submission", { exact: true }).selectOption({ value: "WO-1#1" });
    await expect(built.getByText("Experiment revision 1", { exact: true })).toBeVisible();
    await expect(built).toHaveAttribute("open", "");
    await expect(built.getByText(/procedure-style/)).toHaveCount(0);
  });

  test("an output card for an older order opens that order's submission", async ({ page }) => {
    const cards = page.getByRole("list", { name: "Outputs built" }).getByRole("button", { name: /^Procedure/ });
    const body = tabBody(page, "Procedure");
    await cards.first().click();
    await expect(body.getByText("Being revised", { exact: true })).toBeVisible();
    await expect(body.getByText(EARLIER, { exact: true })).toBeVisible();
    await expect(body.getByLabel("Submission", { exact: true })).toHaveValue("WO-1#1");
    await cards.last().click();
    await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
    await expect(body.getByText(EARLIER)).toHaveCount(0);
  });

  test("at a 1100 px window the picker and Compare share one row", async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 800 });
    const body = tabBody(page, "Procedure");
    const picker = await body.getByLabel("Submission", { exact: true }).boundingBox();
    const compare = await body.getByRole("button", { name: "Compare" }).boundingBox();
    expect(picker && compare).toBeTruthy();
    expect(Math.abs(picker!.y + picker!.height / 2 - (compare!.y + compare!.height / 2))).toBeLessThan(4);
  });

  test("Built from follows the chosen submission's order", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    await body.getByLabel("Submission", { exact: true }).selectOption({ value: "WO-1#1" });
    await expect(body.getByText(EARLIER, { exact: true })).toBeVisible();
    const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
    await built.getByText("Built from", { exact: true }).click();
    await expect(built.getByText("Experiment revision 1", { exact: true })).toBeVisible();
    await expect(built.getByRole("link", { name: "reduction-protocol.txt" })).toHaveCount(0);
  });
});

test("the B12 run plan lists its one submission and has nothing to compare", async ({ page }) => {
  await page.goto(B12);
  await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
  const body = await openTab(page, "Run plan");
  await expect.poll(() => optionTexts(body, "Submission")).toEqual(["WO-B12-RP submission 1, 1 check failed"]);
  const compare = body.getByRole("button", { name: "Compare" });
  await expect(compare).toBeDisabled();
  await expect(body.getByText("Nothing to compare yet.", { exact: true })).toBeVisible();
  await expect(compare).toHaveAccessibleDescription("Nothing to compare yet.");
  const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
  await built.getByText("Built from", { exact: true }).click();
  await expect(built.getByText("No documents cited.", { exact: true })).toBeVisible();
});
