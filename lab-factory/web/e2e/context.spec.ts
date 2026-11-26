import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, attachProtocol, goto } from "./helpers.ts";

/** Opens the workspace header's `Experiment context` and returns the section it shows. */
async function openContext(page: Page) {
  const toggle = page.getByRole("button", { name: "Experiment context" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const section = page.getByRole("region", { name: "Experiment context" });
  await expect(section).toBeVisible();
  return section;
}

test("the experiment context is closed by default and shows the goal, instruments and documents", async ({ page }) => {
  await goto(page, B12);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Experiment context" })).toHaveCount(0);
  const section = await openContext(page);
  await expect(section.getByRole("heading", { name: "Goal" })).toBeVisible();
  await expect(section.getByRole("heading", { name: "Instruments" })).toBeVisible();
  await expect(section.getByRole("list").first().getByRole("listitem").first()).not.toBeEmpty();
  await expect(section.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(section.getByRole("form", { name: "Add a document" })).toBeHidden();
  await section.getByText("Add a document", { exact: true }).click();
  await expect(section.getByRole("form", { name: "Add a document" })).toBeVisible();
  await page.getByRole("button", { name: "Experiment context" }).click();
  await expect(page.getByRole("region", { name: "Experiment context" })).toHaveCount(0);
});

test("an item imported to an experiment is listed in its context and opens in the drawer", async ({ page }) => {
  await goto(page, "/#/connectors");
  const zotero = page.getByRole("region", { name: "Zotero" });
  const title = "Reduction of triarylmethane dyes (sample)";
  await zotero.getByRole("combobox", { name: `Add to, ${title}` }).selectOption({ label: "Reducing Coomassie blue" });
  await zotero.getByRole("button", { name: `Add ${title}` }).click();
  await expect(zotero.getByText(/^Added to Reducing Coomassie blue as revision \d+$/)).toBeVisible();

  await goto(page, COOMASSIE);
  const section = await openContext(page);
  const link = section.getByRole("list", { name: "Experiment documents" }).getByRole("link", { name: title });
  await expect(link).toBeVisible();
  await link.click();
  const drawer = page.getByRole("complementary", { name: "Document" });
  await expect(drawer.getByRole("heading", { level: 2, name: title })).toBeVisible();
  await expect(drawer.getByText("Experiment Reducing Coomassie blue")).toBeVisible();
});

test("an attachment shows in the experiment context, and the revision history lists both revisions", async ({ page }) => {
  await goto(page, COOMASSIE);
  await attachProtocol(page);
  const section = await openContext(page);
  await expect(section.getByRole("list", { name: "Experiment documents" }).getByRole("link", { name: "reduction-protocol.txt" }))
    .toBeVisible();
  await section.getByText("Revision history").click();
  await expect(section.getByRole("list", { name: "Revisions" }).getByRole("listitem")).toHaveCount(2);
});

test("a document added in the experiment context is saved as a new revision and listed", async ({ page }) => {
  await goto(page, B12);
  const section = await openContext(page);
  await section.getByText("Add a document", { exact: true }).click();
  const form = section.getByRole("form", { name: "Add a document" });
  await form.getByLabel("Title").fill("Vial A weighing note");
  await form.getByLabel("Text").fill("Weighed 12.0 mg into vial A.");
  await form.getByRole("button", { name: "Add document" }).click();
  await expect(form.getByRole("status")).toHaveText(/^Saved as revision \d+$/);
  await expect(section.getByRole("link", { name: "Vial A weighing note" })).toBeVisible();
});
