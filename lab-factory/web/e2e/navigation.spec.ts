import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

const SAMPLE = "Sample data. Nothing here is saved or real.";
const NOT_FOUND = "That project or experiment doesn't exist in this lab.";

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Lab" });
}

test("expanding a project and choosing an experiment opens it and marks it current", async ({ page }) => {
  await page.goto("/");
  const toggle = sidebar(page).getByRole("button", { name: "Coomassie reduction" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const experiment = sidebar(page).getByRole("link", { name: "Reducing Coomassie blue" });
  await experiment.click();
  await expect(page).toHaveURL(/#\/projects\/coomassie-reduction\/experiments\/coomassie-run-1$/);
  await expect(experiment).toHaveAttribute("aria-current", "page");
});

test("the sidebar lists its entries in order", async ({ page }) => {
  await page.goto("/");
  const nav = sidebar(page);
  await expect(nav.getByRole("button", { name: "Search" })).toContainText("Ctrl K");
  for (const name of ["New experiment", "New project", "Lab instruments and documents", "Skills", "Connectors",
    "Connect your agent", "Lab settings"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await nav.getByRole("link", { name: "Lab instruments and documents" }).click();
  await expect(page).toHaveURL(/#\/lab$/);
  await nav.getByRole("link", { name: "Connect your agent" }).click();
  await expect(page).toHaveURL(/#\/agents$/);
});

test("the sample indicator is visible on every kind of page", async ({ page }) => {
  for (const hash of ["#/", "#/lab", "#/settings", "#/projects/coomassie-reduction",
    "#/projects/coomassie-reduction/experiments/coomassie-run-1"]) {
    await page.goto("/" + hash);
    await expect(page.getByText(SAMPLE)).toBeVisible();
    await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
  }
});

test("an unknown project or experiment shows the not-found copy and a working link home", async ({ page }) => {
  for (const hash of ["#/projects/nope", "#/projects/nope/experiments/nothing",
    "#/projects/coomassie-reduction/experiments/b12-vial-a"]) {
    await page.goto("/" + hash);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  }
  await page.getByRole("link", { name: "Go to lab home" }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
});

test("Ctrl+K, typing b12 and pressing Enter lands on the B12 project", async ({ page }) => {
  await page.goto("/");
  await expect(sidebar(page).getByRole("button", { name: "Coomassie reduction" })).toBeVisible();
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const input = dialog.getByRole("combobox", { name: "Search the lab" });
  await expect(input).toBeFocused();
  await input.fill("b12");
  await expect(dialog.getByRole("option", { name: /B12 quantification/ })).toBeVisible();
  await expect(dialog.getByRole("option", { name: /B12 quantification/ })).toContainText("Project");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/projects\/b12-quantification$/);
  await expect(dialog).toBeHidden();
});

test("arrow keys move through the results", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const input = page.getByRole("combobox", { name: "Search the lab" });
  await input.fill("b12");
  await expect(page.getByRole("option", { name: /Vitamin B12 absorbance/ })).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("option", { name: /Vitamin B12 absorbance/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/projects\/b12-quantification\/experiments\/b12-vial-a$/);
});

test("the palette says when nothing matches", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search the lab" }).fill("zzzz");
  await expect(page.getByRole("dialog").getByText("No matches")).toBeVisible();
});

test("Escape closes the palette and focus returns to the Search button", async ({ page }) => {
  await page.goto("/");
  const search = sidebar(page).getByRole("button", { name: "Search" });
  await search.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("combobox", { name: "Search the lab" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(search).toBeFocused();
});

test("switching the theme to dark sets data-theme and survives a reload", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await switcher.click();
  await page.getByRole("radio", { name: "Dark" }).check();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  await page.getByRole("radio", { name: "System" }).check();
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
});

test("the lab menu closes on Escape and returns focus to the switcher", async ({ page }) => {
  await page.goto("/");
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await switcher.click();
  await expect(switcher).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("radio", { name: "Researcher" })).toBeChecked();
  await page.keyboard.press("Escape");
  await expect(switcher).toHaveAttribute("aria-expanded", "false");
  await expect(switcher).toBeFocused();
  await switcher.click();
  await page.getByRole("main").click({ position: { x: 5, y: 5 } });
  await expect(page.getByRole("radio", { name: "Researcher" })).toBeHidden();
});

test("the attention badge follows the role", async ({ page }) => {
  await page.goto("/");
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await expect(switcher).toBeVisible();
  await expect(switcher).not.toContainText("need your attention");
  await switcher.click();
  await page.getByRole("radio", { name: "Approver" }).check();
  await expect(switcher).toContainText("1 item needs your attention");
});

test("Reset sample data returns home", async ({ page }) => {
  await page.goto("/#/lab");
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await page.getByRole("button", { name: "Reset sample data" }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(sidebar(page).getByRole("button", { name: "Coomassie reduction" })).toBeVisible();
});
