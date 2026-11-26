import { expect } from "playwright/test";
import type { Page } from "playwright/test";

export const SAMPLE = "Sample data. Nothing here is saved or real.";
export const COOMASSIE = "/#/projects/coomassie-reduction/experiments/coomassie-run-1";
export const B12 = "/#/projects/b12-quantification/experiments/b12-vial-a";

/** Starts a new experiment through the lab home's `Describe your experiment` form and waits for its workspace. */
export async function startExperiment(page: Page, description: string): Promise<void> {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const field = page.getByLabel("Describe your experiment");
  await field.fill(description);
  await page.getByRole("button", { name: "Start experiment" }).click();
  await expect(page).toHaveURL(/#\/projects\/[^/]+\/experiments\/[^/?]+/);
}

/**
 * On the Coomassie workspace: attaches `reduction-protocol.txt`, sends `Here is the protocol`, and waits
 * for the factory's reply, so the rewritten procedure (WO-2) is the newest one.
 */
export async function attachProtocol(page: Page): Promise<void> {
  await page.getByLabel("Attach files").setInputFiles({
    name: "reduction-protocol.txt", mimeType: "text/plain", buffer: Buffer.from("Add the reducing agent dropwise."),
  });
  await page.getByRole("textbox", { name: "Message the factory" }).fill("Here is the protocol");
  await page.getByRole("button", { name: "Send" }).click();
  const reply = "I added reduction-protocol.txt to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.";
  await expect(page.getByText(reply)).toHaveCount(1, { timeout: 20_000 });
  await expect(page.getByText("The factory is working…")).toHaveCount(0);
}

/** Switches `Viewing as` in the lab menu, then closes the menu. The page and its sample data stay. */
export async function viewAs(page: Page, role: "Researcher" | "Approver"): Promise<void> {
  await page.getByRole("navigation", { name: "Lab" }).getByRole("button", { name: /Emory Biophysics/ }).click();
  await page.getByRole("radio", { name: role }).check();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("radio", { name: role })).toBeHidden();
}

/** Goes to a hash route inside the page, so the sample data and the chosen role stay. */
export async function goTo(page: Page, hash: string): Promise<void> {
  await page.evaluate((h) => { window.location.hash = h; }, hash.replace(/^\/?#/, "#"));
}
