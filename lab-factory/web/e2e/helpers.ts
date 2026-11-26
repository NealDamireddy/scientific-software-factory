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
