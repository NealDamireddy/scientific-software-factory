import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, attachProtocol, goTo, viewAs } from "./helpers.ts";

function procedure(page: Page) {
  return page.getByRole("region", { name: "Outputs" }).getByRole("tabpanel", { name: "Procedure" });
}

function attention(page: Page) {
  return page.getByRole("main").getByRole("region", { name: "Needs your attention" });
}

/** Today in the interface's date format, worked out in the page with the same call the interface makes. */
function today(page: Page): Promise<string> {
  return page.evaluate(() => new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }));
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function openB12AsApprover(page: Page) {
  await page.goto(B12);
  await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
  await viewAs(page, "Approver");
  const body = procedure(page);
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
  await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
  return body;
}

async function builtFrom(page: Page) {
  const details = procedure(page).locator("details.hist-built");
  if ((await details.getAttribute("open")) === null) await details.getByText("Built from", { exact: true }).click();
  return details;
}

test("full demo: attach the protocol, then the approver signs off submission 1 by name", async ({ page }) => {
  await page.goto(COOMASSIE);
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
  await attachProtocol(page);
  const body = procedure(page);
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
  await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
  await expect(body.getByRole("button", { name: /^(Approve|Reject) submission/ })).toHaveCount(0);

  await viewAs(page, "Approver");
  await goTo(page, "#/");
  await expect(attention(page).getByRole("link", { name: /Reducing Coomassie blue/ })).toContainText("Waiting for sign-off");
  await attention(page).getByRole("link", { name: /Reducing Coomassie blue/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();

  const reveal = body.getByRole("button", { name: "Approve submission 1", exact: true });
  await expect(reveal).toBeVisible();
  await expect(body.getByRole("button", { name: "Reject submission 1", exact: true })).toBeVisible();
  await reveal.click();
  await expect(reveal).toHaveAttribute("aria-expanded", "true");
  const confirm = body.getByRole("button", { name: "Approve", exact: true });
  await expect(confirm).toBeDisabled();
  await body.getByLabel("Your name").fill("Dr Rivera");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  const date = await today(page);
  await expect(body.getByText(`Signed off by Dr Rivera on ${date}`, { exact: true })).toBeVisible();
  await expect(body.getByRole("button", { name: /^(Approve|Reject)( submission \d+)?$/ })).toHaveCount(0);
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeFocused();
  await expect(body.getByRole("alert")).toHaveCount(0);
  const built = await builtFrom(page);
  await expect(built.getByText(/^Approved by Dr Rivera, submission 1, digest [0-9a-f]{12}, /)).toBeVisible();

  await viewAs(page, "Researcher");
  await goTo(page, "#/");
  const row = attention(page).getByRole("link", { name: /Reducing Coomassie blue/ });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Signed off");
});

test("rejecting B12's procedure with a reason shows the rejection and the factory's acknowledgement", async ({ page }) => {
  const body = await openB12AsApprover(page);
  const reveal = body.getByRole("button", { name: "Reject submission 1", exact: true });
  await reveal.click();
  const confirm = body.getByRole("button", { name: "Reject", exact: true });
  await body.getByLabel("Your name").fill("Dr Rivera");
  await expect(confirm).toBeDisabled();
  await body.getByLabel("Reason").fill("Use the vial B protocol");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect(body.getByText("Rejected by Dr Rivera: Use the vial B protocol", { exact: true })).toBeVisible();
  await expect(body.getByRole("button", { name: /^(Approve|Reject) submission/ })).toHaveCount(0);
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeFocused();
  await expect(page.getByRole("list", { name: "Conversation" }).getByText("Thanks. I’ll revise this to address: Use the vial B protocol", { exact: true })).toBeVisible();
});

test("only one form is open at a time, and Cancel closes it and returns focus to its button", async ({ page }) => {
  const body = await openB12AsApprover(page);
  const approve = body.getByRole("button", { name: "Approve submission 1", exact: true });
  const reject = body.getByRole("button", { name: "Reject submission 1", exact: true });
  await approve.click();
  await expect(body.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
  await reject.click();
  await expect(body.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(body.getByRole("button", { name: "Reject", exact: true })).toBeVisible();
  await expect(approve).toHaveAttribute("aria-expanded", "false");
  await expect(reject).toHaveAttribute("aria-expanded", "true");
  await body.getByRole("button", { name: "Cancel" }).click();
  await expect(body.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
  await expect(reject).toBeFocused();
  await expect(reject).toHaveAttribute("aria-expanded", "false");
});

test("under a listed rule the name is chosen from the list, and approving works", async ({ page }) => {
  await page.goto("/#/settings");
  await page.getByRole("radio", { name: "Only these people" }).check();
  await page.getByLabel("Names, one per line").fill("Dr Rivera");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();

  await goTo(page, B12);
  await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
  await viewAs(page, "Approver");
  const body = procedure(page);
  await body.getByRole("button", { name: "Approve submission 1", exact: true }).click();
  const name = body.getByLabel("Your name");
  await expect(name).toHaveJSProperty("tagName", "SELECT");
  await expect(name.locator("option:not([disabled])")).toHaveText(["Dr Rivera"]);
  await expect(name.locator("option[disabled]")).toHaveText(["Choose your name"]);
  const confirm = body.getByRole("button", { name: "Approve", exact: true });
  await expect(confirm).toBeDisabled();
  await name.selectOption("Dr Rivera");
  await confirm.click();
  await expect(body.getByText(new RegExp(`^Signed off by Dr Rivera on ${escapeRegExp(await today(page))}$`))).toBeVisible();
});

test("three clicks on Approve at once give one sign-off and no alert", async ({ page }) => {
  const body = await openB12AsApprover(page);
  await body.getByRole("button", { name: "Approve submission 1", exact: true }).click();
  await body.getByLabel("Your name").fill("Dr Rivera");
  const confirm = body.getByRole("button", { name: "Approve", exact: true });
  await expect(confirm).toBeEnabled();
  await confirm.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
    button.click();
  });
  await expect(body.getByText(/^Signed off by /)).toHaveCount(1);
  await expect(body.getByText(/^Signed off by Dr Rivera on /)).toBeVisible();
  // Next's route announcer is an empty alert of its own; none other is on the page.
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
  await expect(body.getByRole("alert")).toHaveCount(0);
  const built = await builtFrom(page);
  await expect(built.getByText(/^Approved by /)).toHaveCount(1);
});

test("three submits of the approve form at once, past the button's own state, still give one sign-off", async ({ page }) => {
  const body = await openB12AsApprover(page);
  await body.getByRole("button", { name: "Approve submission 1", exact: true }).click();
  await body.getByLabel("Your name").fill("Dr Rivera");
  await expect(body.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
  await body.getByRole("form", { name: "Approve submission 1" }).evaluate((form: HTMLFormElement) => {
    form.requestSubmit();
    form.requestSubmit();
    form.requestSubmit();
  });
  await expect(body.getByText(/^Signed off by Dr Rivera on /)).toBeVisible();
  await expect(body.getByRole("alert")).toHaveCount(0);
  const built = await builtFrom(page);
  await expect(built.getByText(/^Approved by /)).toHaveCount(1);
});

test("a blank or whitespace-only name keeps Approve disabled, and a blank reason keeps Reject disabled", async ({ page }) => {
  const body = await openB12AsApprover(page);
  await body.getByRole("button", { name: "Approve submission 1", exact: true }).click();
  const approve = body.getByRole("button", { name: "Approve", exact: true });
  const name = body.getByLabel("Your name");
  await expect(approve).toBeDisabled();
  await name.fill("   ");
  await expect(approve).toBeDisabled();
  await name.fill("Dr Rivera");
  await expect(approve).toBeEnabled();

  await body.getByRole("button", { name: "Reject submission 1", exact: true }).click();
  const reject = body.getByRole("button", { name: "Reject", exact: true });
  await body.getByLabel("Your name").fill("Dr Rivera");
  await expect(reject).toBeDisabled();
  await body.getByLabel("Reason").fill("  \n ");
  await expect(reject).toBeDisabled();
  await body.getByLabel("Your name").fill(" ");
  await body.getByLabel("Reason").fill("Use the vial B protocol");
  await expect(reject).toBeDisabled();
  await body.getByLabel("Your name").fill("Dr Rivera");
  await expect(reject).toBeEnabled();
});

test("an earlier submission on show has no sign-off buttons, and they return on the latest", async ({ page }) => {
  await page.goto(COOMASSIE);
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
  await attachProtocol(page);
  await viewAs(page, "Approver");
  const body = procedure(page);
  const buttons = body.getByRole("button", { name: /^(Approve|Reject) submission 1$/ });
  await expect(buttons).toHaveCount(2);
  await body.getByLabel("Submission", { exact: true }).selectOption({ label: "WO-1 submission 1, 1 check failed" });
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();
  await expect(buttons).toHaveCount(0);
  await body.getByRole("button", { name: "Back to the latest" }).click();
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
  await expect(buttons).toHaveCount(2);
});

test("a researcher sees no sign-off controls on a submission waiting for sign-off", async ({ page }) => {
  await page.goto(B12);
  const body = procedure(page);
  await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
  await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
  await expect(body.getByRole("button", { name: /^(Approve|Reject)/ })).toHaveCount(0);
});
