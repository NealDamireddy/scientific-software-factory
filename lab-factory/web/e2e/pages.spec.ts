import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { viewAs, goto } from "./helpers.ts";

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Lab" });
}

test("a new project takes a versioned document, opens it in the drawer and starts an experiment", async ({ page }) => {
  await goto(page, "/");
  await expect(page.getByRole("heading", { name: "What are you working on?" })).toBeVisible();

  const create = page.getByRole("button", { name: "Create project" });
  await expect(create).toBeDisabled();
  await page.getByLabel("Project title").fill("Dye kinetics");
  await page.getByLabel("Goals").fill("Follow how fast a dye fades.");
  await create.click();
  await expect(page).toHaveURL(/#\/projects\/dye-kinetics/);
  await expect(page.getByRole("heading", { name: "Dye kinetics", level: 1 })).toBeVisible();
  await expect(sidebar(page).getByRole("button", { name: "Dye kinetics" })).toBeVisible();

  const aside = page.getByRole("complementary", { name: "Shared with every experiment in this project" });
  const add = aside.getByRole("button", { name: "Add document" });
  await expect(add).toBeDisabled();
  await aside.getByLabel("Title").fill("Rate protocol");
  await aside.getByLabel("Text").fill("Mix the dye with the reducing agent and read every 10 s.");
  await add.click();
  await expect(aside.getByText("Saved as revision 2")).toBeVisible();

  await aside.getByText("Revision history").click();
  await expect(aside.getByRole("list", { name: "Revisions" }).getByRole("listitem")).toHaveCount(2);

  await aside.getByRole("link", { name: "Rate protocol" }).click();
  const drawer = page.getByRole("complementary", { name: "Document" });
  await expect(drawer.getByRole("heading", { name: "Rate protocol" })).toBeFocused();
  await expect(drawer).toContainText("Mix the dye with the reducing agent");
  await expect(drawer).toContainText("Project Dye kinetics");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/#\/projects\/dye-kinetics$/);

  await page.getByLabel("Describe your experiment").fill("Measure the rate of fading");
  await page.getByRole("button", { name: "Start experiment" }).click();
  await expect(page).toHaveURL(/#\/projects\/dye-kinetics\/experiments\/.+/);
});

test("the project page shows each experiment's status line", async ({ page }) => {
  await goto(page, "/#/projects/coomassie-reduction");
  await expect(page.getByRole("link", { name: "Reducing Coomassie blue" })).toBeVisible();
  await expect(page.getByText("Being revised")).toBeVisible();
});

test("the drawer says when a document isn't there, and Close removes it from the route", async ({ page }) => {
  await goto(page, "/#/lab?doc=nope");
  const drawer = page.getByRole("complementary", { name: "Document" });
  await expect(drawer.getByText("That document isn't here.")).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(page).toHaveURL(/#\/lab$/);
});

test("the lab page shows range strips, commands and lab documents", async ({ page }) => {
  await goto(page, "/#/lab");
  const strip = page.getByRole("img", { name: "Wavelength, allowed 400 to 700 nm" });
  await expect(strip).toBeVisible();
  await expect(strip.locator(".range-marker")).toHaveCount(0);
  await expect(page.getByText("Needs wavelength. Optional: integration time.")).toBeVisible();
  await expect(page.getByText("Revision history")).toBeVisible();
});

test("the approver's home lists the experiment waiting for sign-off, the researcher's is empty", async ({ page }) => {
  await goto(page, "/");
  await expect(page.getByRole("heading", { name: "Needs your attention" })).toBeVisible();
  await expect(page.getByText("Nothing needs you right now.")).toBeVisible();
  await viewAs(page, "Approver");
  const link = page.getByRole("main").getByRole("link", { name: /Vitamin B12 absorbance/ });
  await expect(link).toBeVisible();
  await expect(link).toContainText("Waiting for sign-off");
  await expect(page.getByText("Nothing needs you right now.")).toHaveCount(0);
});

test("the sign-off rule is saved and still there after leaving settings", async ({ page }) => {
  await goto(page, "/#/settings");
  await expect(page.getByRole("radio", { name: "Anyone who gives their name" })).toBeChecked();
  await page.getByRole("radio", { name: "Only these people" }).check();
  await page.getByLabel("Names, one per line").fill("Dr Rivera");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await sidebar(page).getByRole("link", { name: "Lab instruments and documents" }).click();
  await sidebar(page).getByRole("link", { name: "Lab settings" }).click();
  await expect(page.getByRole("radio", { name: "Only these people" })).toBeChecked();
  await expect(page.getByLabel("Names, one per line")).toHaveValue("Dr Rivera");
});

test("blank names are refused with a message that goes away when the person edits", async ({ page }) => {
  await goto(page, "/#/settings");
  await page.getByRole("radio", { name: "Only these people" }).check();
  await page.getByRole("button", { name: "Save settings" }).click();
  const form = page.getByRole("form", { name: "Lab settings" });
  await expect(form.getByRole("alert")).toContainText("Add at least one name");
  await page.getByLabel("Names, one per line").fill("Dr Rivera");
  await expect(form.getByRole("alert")).toHaveCount(0);

  // Typed names survive a trip to the other rule and back.
  await page.getByRole("radio", { name: "Anyone who gives their name" }).check();
  await page.getByRole("radio", { name: "Only these people" }).check();
  await expect(page.getByLabel("Names, one per line")).toHaveValue("Dr Rivera");
});

test("a .md file fills the title and text, and a repeated title is listed twice", async ({ page }) => {
  await goto(page, "/#/projects/coomassie-reduction");
  const aside = page.getByRole("complementary", { name: "Shared with every experiment in this project" });
  await aside.getByLabel("Or fill it from a .txt or .md file").setInputFiles({
    name: "twin-notes.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Notes\nFirst wording."),
  });
  await expect(aside.getByLabel("Title")).toHaveValue("twin-notes");
  await expect(aside.getByLabel("Text")).toHaveValue("# Notes\nFirst wording.");
  await aside.getByRole("button", { name: "Add document" }).click();
  await expect(aside.getByRole("status")).toContainText("Saved as revision");
  await expect(aside.getByRole("link", { name: "twin-notes" })).toHaveCount(1);

  await aside.getByLabel("Title").fill("twin-notes");
  await aside.getByLabel("Text").fill("Second wording.");
  await aside.getByRole("button", { name: "Add document" }).click();
  await expect(aside.getByRole("link", { name: "twin-notes" })).toHaveCount(2);
});

test("saving a document again with identical content says it was already saved", async ({ page }) => {
  await goto(page, "/#/projects/coomassie-reduction");
  const aside = page.getByRole("complementary", { name: "Shared with every experiment in this project" });
  for (const expected of [/^Saved as revision \d+$/, /^Already saved as revision \d+$/]) {
    await aside.getByLabel("Title").fill("Same again");
    await aside.getByLabel("Text").fill("Exactly the same text.");
    await aside.getByRole("button", { name: "Add document" }).click();
    await expect(aside.getByRole("status")).toHaveText(expected);
  }
});

test("only the wavelength strip is drawn with the spectrum", async ({ page }) => {
  await goto(page, "/#/lab");
  const wavelength = page.getByRole("img", { name: /^Wavelength, allowed / }).first();
  await expect(wavelength.locator(".range-track .range-spectrum")).toHaveCSS("background-image", /linear-gradient/);
  // The lab's 400 to 700 nm instrument shows the spectrum across the whole track.
  await expect(wavelength.locator(".range-spectrum")).toHaveAttribute("style", /left: 0%; width: 100%/);
  const temperature = page.getByRole("img", { name: /^Temperature, allowed / }).first();
  await expect(temperature.locator(".range-spectrum")).toHaveCount(0);
  await expect(temperature.locator(".range-track")).toHaveCSS("background-image", "none");
});
