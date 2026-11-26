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

    await built.getByRole("link", { name: "reduction-protocol.txt" }).click();
    const drawer = page.getByRole("complementary", { name: "Document" });
    await expect(drawer.getByRole("heading", { level: 2, name: "reduction-protocol.txt" })).toBeVisible();
    await expect(drawer).toContainText("Add the reducing agent dropwise.");
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
