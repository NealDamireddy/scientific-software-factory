import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Lab" });
}

async function viewAs(page: Page, role: "Researcher" | "Approver") {
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await page.getByRole("radio", { name: role }).check();
  await page.keyboard.press("Escape");
}

test("a new project takes a versioned document, opens it in the drawer and starts an experiment", async ({ page }) => {
  await page.goto("/");
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
  await page.goto("/#/projects/coomassie-reduction");
  await expect(page.getByRole("link", { name: "Reducing Coomassie blue" })).toBeVisible();
  await expect(page.getByText("Being revised")).toBeVisible();
});

test("the drawer says when a document isn't there, and Close removes it from the route", async ({ page }) => {
  await page.goto("/#/lab?doc=nope");
  const drawer = page.getByRole("complementary", { name: "Document" });
  await expect(drawer.getByText("That document isn't here.")).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(page).toHaveURL(/#\/lab$/);
});

test("the lab page shows range strips, commands and lab documents", async ({ page }) => {
  await page.goto("/#/lab");
  const strip = page.getByRole("img", { name: "Wavelength 400–700 nm, allowed 400 to 700 nm" });
  await expect(strip).toBeVisible();
  await expect(strip.locator(".range-marker")).toHaveAttribute("style", /left: 50%/);
  await expect(page.getByText("Needs wavelength. Optional: integration time.")).toBeVisible();
  await expect(page.getByText("Revision history")).toBeVisible();
});

test("the approver's home lists the experiment waiting for sign-off, the researcher's is empty", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Needs your attention" })).toBeVisible();
  await expect(page.getByText("Nothing needs you right now.")).toBeVisible();
  await viewAs(page, "Approver");
  const link = page.getByRole("main").getByRole("link", { name: /Vitamin B12 absorbance/ });
  await expect(link).toBeVisible();
  await expect(link).toContainText("Waiting for sign-off");
  await expect(page.getByText("Nothing needs you right now.")).toHaveCount(0);
});

test("the sign-off rule is saved and still there after leaving settings", async ({ page }) => {
  await page.goto("/#/settings");
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
