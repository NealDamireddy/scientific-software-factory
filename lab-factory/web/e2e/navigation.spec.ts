import { expect, test } from "playwright/test";
import { goto, ready, viewAs } from "./helpers.ts";
import type { Page } from "playwright/test";

const SAMPLE = "Sample data. Nothing here is saved or real.";
const NOT_FOUND = "That project or experiment doesn't exist in this lab.";

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Lab" });
}

test("expanding a project and choosing an experiment opens it and marks it current", async ({ page }) => {
  await goto(page, "/");
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
  await goto(page, "/");
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
  await goto(page, "/");
  const search = sidebar(page).getByRole("button", { name: "Search", exact: true });
  await expect(search).toContainText("Ctrl K");
  await expect(search).toHaveAttribute("aria-keyshortcuts", "Control+K Meta+K");
  await expect(search).toHaveAttribute("aria-haspopup", "dialog");
  await expect(search.locator("kbd")).toHaveAttribute("aria-hidden", "true");
});

test("the sample indicator is in the viewport on every kind of page", async ({ page }) => {
  for (const hash of ["#/", "#/lab", "#/settings", "#/projects/coomassie-reduction",
    "#/projects/coomassie-reduction/experiments/coomassie-run-1"]) {
    await goto(page, "/" + hash);
    await expect(page.getByText(SAMPLE)).toBeInViewport();
    await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
  }
});

test.describe("on a short screen", () => {
  test.use({ viewport: { width: 1024, height: 600 } });

  test("the sample indicator stays in the viewport with both projects expanded", async ({ page }) => {
    await goto(page, "/");
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
    await goto(page, "/");
    await sidebar(page).getByRole("button", { name: "Navigation" }).click();
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

  test("with the document drawer open the indicator stays on top, and the drawer's end clears it", async ({ page }) => {
    await goto(page, "/#/lab");
    const link = page.getByRole("main").locator("a.pg-row").first();
    await link.click();
    const drawer = page.getByRole("complementary", { name: "Document" });
    await expect(drawer.getByRole("heading", { level: 2 })).toBeVisible();
    const indicator = page.locator(".sample-indicator");
    await expect(indicator).toBeInViewport({ ratio: 1 });
    const onTop = await indicator.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return top !== null && el.contains(top);
    });
    expect(onTop).toBe(true);
    // Scrolled to its end, the drawer's last text sits above the indicator.
    await drawer.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    const text = await drawer.locator(".drawer-text").boundingBox();
    const box = await indicator.boundingBox();
    expect(text!.y + text!.height).toBeLessThanOrEqual(box!.y + 0.5);
  });
});

test("an unknown project or experiment shows the not-found copy and a working link home", async ({ page }) => {
  for (const hash of ["#/projects/nope", "#/projects/nope/experiments/nothing",
    "#/projects/coomassie-reduction/experiments/b12-vial-a"]) {
    await goto(page, "/" + hash);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  }
  await page.getByRole("link", { name: "Go to lab home" }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
});

test("Ctrl+K, typing b12 and pressing Enter lands on the B12 project", async ({ page }) => {
  await goto(page, "/");
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
  await goto(page, "/");
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
  await goto(page, "/");
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
  await goto(page, "/");
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
  await goto(page, "/");
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
  await goto(page, "/");
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => { window.location.hash = "#/lab"; });
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("a route change already under way when the palette opens doesn't close it", async ({ page }) => {
  await goto(page, "/");
  // The hash changes and Ctrl+K arrives in the same task, so the hashchange event fires after the open.
  await page.evaluate(() => {
    window.location.hash = "#/lab";
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
  });
  await expect(page).toHaveURL(/#\/lab$/);
  await expect(page.getByRole("heading", { level: 1, name: "Lab instruments and documents" })).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Search the lab" })).toBeFocused();
});

test("when the trigger is gone after choosing a result, focus goes to the Search button", async ({ page }) => {
  await goto(page, "/#/projects/nope");
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
    await goto(page, "/");
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox", { name: "Search the lab" }).fill("e");
    const options = page.getByRole("dialog").getByRole("option");
    await expect(options.first()).toBeVisible();
    const last = options.last();
    await expect(last).not.toBeInViewport();
    await page.keyboard.press("ArrowUp");
    await expect(last).toHaveAttribute("aria-selected", "true");
    await expect(last).toBeInViewport({ ratio: 1 });
  });
});

test("a collapsed project opens again when the route moves into it", async ({ page }) => {
  await goto(page, "/#/projects/coomassie-reduction");
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
  await goto(page, "/");
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
  await goto(page, "/");
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await switcher.click();
  await page.getByRole("radio", { name: "Dark" }).check();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await ready(page);
  await expect(html).toHaveAttribute("data-theme", "dark");
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  await page.getByRole("radio", { name: "System" }).check();
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
});

test("the lab menu closes on Escape and returns focus to the switcher", async ({ page }) => {
  await goto(page, "/");
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
  await goto(page, "/");
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await switcher.click();
  await expect(page.getByRole("radio", { name: "Researcher" })).toBeFocused();
  await page.getByRole("radio", { name: "Approver" }).check();
  await page.keyboard.press("Escape");
  await switcher.click();
  await expect(page.getByRole("radio", { name: "Approver" })).toBeFocused();
});

test("the attention badge follows the role", async ({ page }) => {
  await goto(page, "/");
  const switcher = sidebar(page).getByRole("button", { name: /Emory Biophysics/ });
  await expect(switcher).toBeVisible();
  await expect(switcher).not.toContainText("need your attention");
  await switcher.click();
  await page.getByRole("radio", { name: "Approver" }).check();
  await expect(switcher).toContainText("1 item needs your attention");
});

test("Reset sample data returns home", async ({ page }) => {
  await goto(page, "/#/lab");
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await page.getByRole("button", { name: "Reset sample data" }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(sidebar(page).getByRole("button", { name: "Coomassie reduction" })).toBeVisible();
});

test("Reset sample data also returns the role to researcher", async ({ page }) => {
  await goto(page, "/#/");
  await viewAs(page, "Approver");
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await expect(page.getByRole("radio", { name: "Approver" })).toBeChecked();
  await page.getByRole("button", { name: "Reset sample data" }).click();
  await expect(page.getByRole("radio", { name: "Approver" })).toBeHidden();
  await sidebar(page).getByRole("button", { name: /Emory Biophysics/ }).click();
  await expect(page.getByRole("radio", { name: "Researcher" })).toBeChecked();
});

test.describe("on an Apple computer", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "platform", { get: () => "MacIntel" });
    });
  });

  test("the Search shortcut reads ⌘K", async ({ page }) => {
    await goto(page, "/");
    const search = sidebar(page).getByRole("button", { name: "Search", exact: true });
    await expect(search.locator("kbd")).toHaveText("⌘K");
  });
});

test("a deep link never shows the lab home before its own view, even when scripts are slow", async ({ page }) => {
  await page.route("**/_next/static/**/*.js", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await route.continue();
  });
  // Every frame is checked from the very first paint, before any app script runs.
  await page.addInitScript(() => {
    const w = window as unknown as { __sawHome: boolean };
    w.__sawHome = false;
    const look = () => {
      if (document.body?.textContent?.includes("What are you working on?")) w.__sawHome = true;
    };
    const everyFrame = () => { look(); requestAnimationFrame(everyFrame); };
    new MutationObserver(look).observe(document, { childList: true, subtree: true, characterData: true });
    requestAnimationFrame(everyFrame);
  });
  // A raw goto on purpose: the test watches the page before the app is ready.
  await page.goto("/#/projects/coomassie-reduction/experiments/coomassie-run-1");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible({ timeout: 20_000 });
  expect(await page.evaluate(() => (window as unknown as { __sawHome: boolean }).__sawHome)).toBe(false);
  await expect(page.locator('[data-ready="true"]')).toHaveCount(1);
});

test("the prerendered page has the title and the main landmark, and nothing in it is clickable yet", async ({ request }) => {
  const html = await (await request.get("/")).text();
  expect(html.includes("<title>Lab Factory</title>")).toBe(true);
  expect(/<main[^>]*class="content"/.test(html)).toBe(true);
  expect(html.includes("What are you working on?")).toBe(false);
  expect(html.includes('data-ready="false"')).toBe(true);
  expect(/<nav[^>]*inert/.test(html)).toBe(true);
});

test.describe("on a short screen, the sidebar's New links", () => {
  test.use({ viewport: { width: 1280, height: 500 } });

  test("New project and New experiment move focus to their field, even when the page doesn't change", async ({ page }) => {
    await goto(page, "/");
    await sidebar(page).getByRole("link", { name: "New project" }).click();
    const title = page.getByRole("main").getByLabel("Project title");
    await expect(title).toBeFocused();
    await expect(title).toBeInViewport();

    // Already on the lab home: the hash stays the same, and focus still moves.
    await sidebar(page).getByRole("link", { name: "New experiment" }).click();
    const describe = page.getByRole("main").getByLabel("Describe your experiment");
    await expect(describe).toBeFocused();
    await expect(describe).toBeInViewport();
    await sidebar(page).getByRole("link", { name: "New project" }).click();
    await expect(title).toBeFocused();
    await expect(title).toBeInViewport();

    // Inside a project, New experiment leads to that project's form.
    await goto(page, "/#/projects/coomassie-reduction/experiments/coomassie-run-1");
    await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
    await sidebar(page).getByRole("link", { name: "New experiment" }).click();
    await expect(page).toHaveURL(/#\/projects\/coomassie-reduction$/);
    await expect(page.getByRole("main").getByLabel("Describe your experiment")).toBeFocused();
    await expect(page.getByRole("main").getByLabel("Describe your experiment")).toBeInViewport();
  });
});

test("the desktop experiment title stays readable across the sidebar breakpoint", async ({ page }) => {
  await goto(page, "/#/projects/coomassie-reduction/experiments/coomassie-run-1");
  const title = page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" });
  for (const width of [1099, 1100, 1120]) {
    await page.setViewportSize({ width, height: 720 });
    await expect(title).toBeVisible();
    await expect.poll(() => title.evaluate((el) => el.clientWidth / el.scrollWidth)).toBeGreaterThan(0.95);
  }
});

test("on a phone the workspace opens above the fold and navigation remains accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await goto(page, "/#/projects/coomassie-reduction/experiments/coomassie-run-1");
  const title = page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" });
  await expect(title).toBeInViewport();
  expect((await title.boundingBox())!.y).toBeLessThan(150);
  const nav = sidebar(page);
  const menu = nav.getByRole("button", { name: "Navigation" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  await nav.getByRole("link", { name: "Skills" }).click();
  await expect(page.getByRole("heading", { name: "Skills", level: 1 })).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "false");
});
