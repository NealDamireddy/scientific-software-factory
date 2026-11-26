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
  await expect(nav.getByRole("button", { name: "Coomassie reduction" })).toBeVisible();
  const entries = await nav.locator(".lab-switcher-name, .sidebar-heading, .sidebar-item-label")
    .filter({ visible: true }).allTextContents();
  expect(entries).toEqual(["Emory Biophysics", "Search", "New experiment", "Projects", "Coomassie reduction",
    "B12 quantification", "New project", "Lab instruments and documents", "Skills", "Connectors",
    "Connect your agent", "Lab settings"]);
  await nav.getByRole("link", { name: "Lab instruments and documents" }).click();
  await expect(page).toHaveURL(/#\/lab$/);
  await nav.getByRole("link", { name: "Connect your agent" }).click();
  await expect(page).toHaveURL(/#\/agents$/);
});

test("the Search button is named Search and announces its shortcut and dialog", async ({ page }) => {
  await page.goto("/");
  const search = sidebar(page).getByRole("button", { name: "Search", exact: true });
  await expect(search).toContainText("Ctrl K");
  await expect(search).toHaveAttribute("aria-keyshortcuts", "Control+K Meta+K");
  await expect(search).toHaveAttribute("aria-haspopup", "dialog");
  await expect(search.locator("kbd")).toHaveAttribute("aria-hidden", "true");
});

test("the sample indicator is in the viewport on every kind of page", async ({ page }) => {
  for (const hash of ["#/", "#/lab", "#/settings", "#/projects/coomassie-reduction",
    "#/projects/coomassie-reduction/experiments/coomassie-run-1"]) {
    await page.goto("/" + hash);
    await expect(page.getByText(SAMPLE)).toBeInViewport();
    await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
  }
});

test.describe("on a short screen", () => {
  test.use({ viewport: { width: 1024, height: 600 } });

  test("the sample indicator stays in the viewport with both projects expanded", async ({ page }) => {
    await page.goto("/");
    for (const name of ["Coomassie reduction", "B12 quantification"]) {
      const toggle = sidebar(page).getByRole("button", { name });
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
    }
    await expect(page.getByText(SAMPLE)).toBeInViewport({ ratio: 1 });
    await sidebar(page).getByRole("link", { name: "Vitamin B12 absorbance" }).scrollIntoViewIfNeeded();
    await expect(page.getByText(SAMPLE)).toBeInViewport({ ratio: 1 });
    await expect(sidebar(page).getByRole("link", { name: "Lab settings" })).toBeInViewport({ ratio: 1 });
  });
});

test.describe("on a narrow screen", () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test("the sample indicator stays in the viewport after scrolling and covers nothing", async ({ page }) => {
    await page.goto("/");
    for (const name of ["Coomassie reduction", "B12 quantification"]) {
      await sidebar(page).getByRole("button", { name }).click();
    }
    const indicator = page.getByText(SAMPLE);
    await expect(indicator).toBeInViewport({ ratio: 1 });
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));
    await expect(indicator).toBeInViewport({ ratio: 1 });
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect(indicator).toBeInViewport({ ratio: 1 });
    // Scrolled to the end, the page content ends above the indicator.
    const main = await page.getByRole("main").boundingBox();
    const box = await page.locator(".sample-indicator").boundingBox();
    expect(main!.y + main!.height).toBeLessThanOrEqual(box!.y + 0.5);
  });
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

test("typing a new query and pressing Enter at once never follows the old results", async ({ page }) => {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { seenHashes: string[] }).seenHashes = seen;
    window.addEventListener("hashchange", () => seen.push(location.hash));
  });
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const input = page.getByRole("combobox", { name: "Search the lab" });
  await input.fill("vitamin");
  await expect(page.getByRole("option", { name: /Vitamin B12 absorbance/ })).toBeVisible();
  await input.fill("coomassie");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/projects\/coomassie-reduction$/);
  await expect(page.getByRole("dialog")).toBeHidden();
  const seen = await page.evaluate(() => (window as unknown as { seenHashes: string[] }).seenHashes);
  expect(seen.filter((h) => h.includes("b12"))).toEqual([]);
});

test("clicking inside the palette keeps focus there: Escape closes and Tab stays inside", async ({ page }) => {
  await page.goto("/");
  const search = sidebar(page).getByRole("button", { name: "Search", exact: true });
  await search.click();
  const dialog = page.getByRole("dialog");
  const input = dialog.getByRole("combobox", { name: "Search the lab" });
  await expect(input).toBeFocused();
  await dialog.getByText("Find projects, experiments").click();
  const inDialog = () => page.evaluate(() => !!document.activeElement?.closest("[role=dialog]"));
  expect(await inDialog()).toBe(true);
  for (const key of ["Tab", "Shift+Tab", "Tab", "Tab", "Shift+Tab"]) {
    await page.keyboard.press(key);
    expect(await inDialog()).toBe(true);
  }
  await expect(page.getByRole("main")).toHaveAttribute("inert", "");
  await expect(sidebar(page)).toHaveAttribute("inert", "");
  await dialog.getByText("Find projects, experiments").click();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(search).toBeFocused();
  await expect(page.getByRole("main")).not.toHaveAttribute("inert", /.*/);
});

test("the palette closes when the route changes", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => { window.location.hash = "#/lab"; });
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("when the trigger is gone after choosing a result, focus goes to the Search button", async ({ page }) => {
  await page.goto("/#/projects/nope");
  const home = page.getByRole("link", { name: "Go to lab home" });
  await home.focus();
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search the lab" }).fill("b12");
  await expect(page.getByRole("option", { name: /B12 quantification/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/projects\/b12-quantification$/);
  await expect(sidebar(page).getByRole("button", { name: "Search", exact: true })).toBeFocused();
});

test.describe("with many results", () => {
  test.use({ viewport: { width: 1024, height: 500 } });

  test("the active option scrolls into view", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox", { name: "Search the lab" }).fill("e");
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible();
    const last = options.last();
    await expect(last).not.toBeInViewport();
    await page.keyboard.press("ArrowUp");
    await expect(last).toHaveAttribute("aria-selected", "true");
    await expect(last).toBeInViewport({ ratio: 1 });
  });
});

test("a collapsed project opens again when the route moves into it", async ({ page }) => {
  await page.goto("/#/projects/coomassie-reduction");
  const toggle = sidebar(page).getByRole("button", { name: "Coomassie reduction" });
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search the lab" }).fill("reducing coomassie");
  await expect(page.getByRole("option", { name: /Reducing Coomassie blue/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/projects\/coomassie-reduction\/experiments\/coomassie-run-1$/);
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const current = sidebar(page).getByRole("link", { name: "Reducing Coomassie blue" });
  await expect(current).toHaveAttribute("aria-current", "page");
  await expect(current).toBeVisible();
});

test("Escape closes the palette and focus returns to the Search button", async ({ page }) => {
  await page.goto("/");
  const search = sidebar(page).getByRole("button", { name: "Search", exact: true });
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

test("the lab menu opens with focus on the checked role", async ({ page }) => {
  await page.goto("/");
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await switcher.click();
  await expect(page.getByRole("radio", { name: "Researcher" })).toBeFocused();
  await page.getByRole("radio", { name: "Approver" }).check();
  await page.keyboard.press("Escape");
  await switcher.click();
  await expect(page.getByRole("radio", { name: "Approver" })).toBeFocused();
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
