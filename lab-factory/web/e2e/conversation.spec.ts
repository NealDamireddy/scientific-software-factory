import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, SAMPLE, startExperiment } from "./helpers.ts";

const SAMPLE_REPLY = "This is sample data, so the factory can’t act on that here. In the live app it would answer and update the outputs.";
const FADING = "Measure the rate of fading and simulate it";
// The sample build plays one activity line every 600 ms, so a whole build takes several seconds.
const BUILD_MS = 20_000;

function conversation(page: Page) {
  return page.getByRole("list", { name: "Conversation" });
}

function panel(page: Page) {
  return page.getByRole("region", { name: "Outputs" });
}

function activity(page: Page) {
  return page.getByRole("list", { name: "Activity" });
}

/** Records whether an empty activity log (`0 steps`) ever appears from now on. */
async function watchForEmptyLog(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __emptyLog: boolean };
    w.__emptyLog = false;
    new MutationObserver(() => {
      if (document.body.innerText.includes("0 steps")) w.__emptyLog = true;
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  });
}

async function sawEmptyLog(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __emptyLog: boolean }).__emptyLog);
}

async function tabNames(page: Page): Promise<string[]> {
  return panel(page).getByRole("tablist").getByRole("tab").allTextContents();
}

// ---------------------------------------------------------------- a new experiment

test.describe("a new experiment", () => {
  test("proposes outputs, builds the chosen ones and streams the activity", async ({ page }) => {
    await startExperiment(page, FADING);
    const procedure = page.getByRole("checkbox", { name: "Procedure" });
    const app = page.getByRole("checkbox", { name: "Analysis app" });
    const sim = page.getByRole("checkbox", { name: "Simulation" });
    await expect(procedure).toBeChecked();
    await expect(app).toBeChecked();
    await expect(sim).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Run plan" })).toHaveCount(0);

    await sim.uncheck();
    await page.getByRole("button", { name: "Build these" }).click();

    // The lines arrive one at a time: the first is there while the last is not yet.
    const log = activity(page);
    await expect(log.getByText("Read lab context (revision 1)")).toBeVisible();
    await expect(log.getByText("Ran 3 reference cases")).toHaveCount(0);
    await expect(page.getByText(SAMPLE)).toBeInViewport();
    await expect(log.getByRole("listitem").last()).toContainText("Ran 3 reference cases", { timeout: BUILD_MS });
    await expect(log.getByText("Wrote simulation")).toHaveCount(0);
    await expect(page.getByText("Building: Procedure, Analysis app")).toBeVisible();

    await expect(panel(page)).toBeVisible();
    await expect.poll(() => tabNames(page)).toEqual(["Procedure", "Analysis app", "Results"]);
  });

  test("double-clicking Build these builds once", async ({ page }) => {
    await startExperiment(page, FADING);
    const build = page.getByRole("button", { name: "Build these" });
    // Several clicks in the same task, so the extra ones hit the same button before React re-renders.
    await build.evaluate((b: HTMLElement) => { b.click(); b.click(); b.click(); });
    const log = activity(page);
    await expect(log.getByRole("listitem").last()).toContainText("Wrote simulation", { timeout: BUILD_MS });
    await expect(page.getByText(/^Built\./)).toHaveCount(1);
    const lines = await log.getByRole("listitem").allTextContents();
    expect(new Set(lines).size).toBe(lines.length);
    expect(lines.filter((l) => l.includes("Read lab context"))).toHaveLength(1);
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  });
});

// ---------------------------------------------------------------- the seeded Coomassie workspace

test.describe("the Coomassie workspace", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(COOMASSIE);
    await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
  });

  test("shows the breadcrumb with the project as a link", async ({ page }) => {
    const link = page.getByRole("main").getByRole("link", { name: "Coomassie reduction" });
    await expect(link).toHaveAttribute("href", "#/projects/coomassie-reduction");
  });

  test("an accepted proposal shows what was built and no controls", async ({ page }) => {
    await expect(page.getByText("Building: Procedure, Analysis app, Simulation")).toBeVisible();
    await expect(page.getByRole("button", { name: "Build these" })).toHaveCount(0);
    await expect(conversation(page).getByRole("checkbox")).toHaveCount(0);
  });

  test("a historical activity log is closed and opens to its steps", async ({ page }) => {
    const summary = page.getByText("7 steps", { exact: true });
    await expect(summary).toBeVisible();
    const failed = activity(page).getByText(/^Ran \d+ checks: 1 failed$/);
    await expect(failed).toBeHidden();
    await summary.click();
    await expect(failed).toBeVisible();
    await expect(activity(page).getByText("step 4: citations: no citation")).toBeVisible();
    await expect(activity(page).getByRole("listitem")).toHaveCount(7);
    await expect(activity(page).getByRole("listitem").nth(3)).toContainText("Failed");
  });

  test("the panel has a tab per output and opens on the first", async ({ page }) => {
    await expect(panel(page)).toBeVisible();
    await expect.poll(() => tabNames(page)).toEqual(["Procedure", "Analysis app", "Results", "Simulation"]);
    const first = panel(page).getByRole("tab", { name: "Procedure" });
    await expect(first).toHaveAttribute("aria-selected", "true");
    await expect(panel(page).getByRole("tabpanel", { name: "Procedure" })).toBeVisible();
    await first.focus();
    await page.keyboard.press("ArrowRight");
    const app = panel(page).getByRole("tab", { name: "Analysis app" });
    await expect(app).toBeFocused();
    await expect(app).toHaveAttribute("aria-selected", "true");
    await expect(panel(page).getByRole("tabpanel", { name: "Analysis app" })).toBeVisible();
    await page.keyboard.press("End");
    await expect(panel(page).getByRole("tab", { name: "Simulation" })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowRight");
    await expect(first).toHaveAttribute("aria-selected", "true");
  });

  test("an output reference opens the panel on its tab", async ({ page }) => {
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(panel(page)).toBeHidden();
    await conversation(page).getByRole("button", { name: /^Simulation/ }).click();
    await expect(panel(page)).toBeVisible();
    await expect(panel(page).getByRole("tab", { name: "Simulation" })).toHaveAttribute("aria-selected", "true");
    await expect(panel(page).getByRole("heading", { name: "Simulation" })).toBeVisible();
  });

  test("closing the panel and choosing Show outputs reopens it", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Show outputs" })).toHaveCount(0);
    await page.getByRole("button", { name: "Close panel" }).click();
    await expect(panel(page)).toBeHidden();
    const show = page.getByRole("button", { name: "Show outputs" });
    await expect(show).toBeFocused();
    await show.click();
    await expect(panel(page)).toBeVisible();
    await expect(show).toHaveCount(0);
  });

  test("Send is disabled for a blank or whitespace message", async ({ page }) => {
    const box = page.getByRole("textbox", { name: "Message the factory" });
    const send = page.getByRole("button", { name: "Send" });
    await expect(send).toBeDisabled();
    await box.fill("   \n  ");
    await expect(send).toBeDisabled();
    await box.fill("hello");
    await expect(send).toBeEnabled();
  });

  test("sending hello shows the sample reply once", async ({ page }) => {
    await page.getByRole("textbox", { name: "Message the factory" }).fill("hello");
    await watchForEmptyLog(page);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(SAMPLE_REPLY)).toBeVisible();
    await expect(page.getByText("0 steps")).toHaveCount(0);
    expect(await sawEmptyLog(page)).toBe(false);
    await expect(page.getByText(SAMPLE_REPLY)).toHaveCount(1);
    await expect(conversation(page).getByText("hello", { exact: true })).toHaveCount(1);
    await expect(page.getByRole("textbox", { name: "Message the factory" })).toHaveValue("");
  });

  test("Enter sends and Shift+Enter makes a new line", async ({ page }) => {
    const box = page.getByRole("textbox", { name: "Message the factory" });
    await box.fill("first line");
    await box.press("Shift+Enter");
    await box.pressSequentially("second line");
    await expect(box).toHaveValue("first line\nsecond line");
    await box.press("Enter");
    await expect(page.getByText(SAMPLE_REPLY)).toHaveCount(1);
    await expect(conversation(page).getByText(/first line\s+second line/)).toHaveCount(1);
  });

  test("attached files show as removable chips", async ({ page }) => {
    const send = page.getByRole("button", { name: "Send" });
    await page.getByLabel("Attach files").setInputFiles([
      { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("A") },
      { name: "b.txt", mimeType: "text/plain", buffer: Buffer.from("B") },
    ]);
    await expect(send).toBeEnabled();
    await page.getByRole("button", { name: "Remove a.txt" }).click();
    await expect(page.getByRole("button", { name: "Remove a.txt" })).toHaveCount(0);
    await page.getByRole("button", { name: "Remove b.txt" }).click();
    await expect(send).toBeDisabled();
  });

  test("attaching the protocol streams the rewrite while the factory is working", async ({ page }) => {
    await page.getByLabel("Attach files").setInputFiles({
      name: "reduction-protocol.txt", mimeType: "text/plain", buffer: Buffer.from("Add the reducing agent dropwise."),
    });
    await page.getByRole("textbox", { name: "Message the factory" }).fill("Here is the protocol");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByRole("status").filter({ hasText: "The factory is working…" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
    await expect(page.getByText(SAMPLE)).toBeInViewport();
    await expect(page.getByText("Read your attachment")).toBeVisible();
    const reply = "I added reduction-protocol.txt to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.";
    await expect(page.getByText(reply)).toHaveCount(1, { timeout: BUILD_MS });
    await expect(page.getByText("The factory is working…")).toHaveCount(0);
    await expect(conversation(page).getByText("Here is the protocol", { exact: true })).toHaveCount(1);
    await expect(conversation(page).getByText("reduction-protocol.txt", { exact: true })).toHaveCount(1);
    const lines = await page.getByText("Rewrote procedure").count();
    expect(lines).toBe(1);
  });
});

for (const width of [1120, 1280]) {
  test(`every panel tab is fully inside the panel at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(COOMASSIE);
    await expect.poll(() => tabNames(page)).toEqual(["Procedure", "Analysis app", "Results", "Simulation"]);
    await expect(panel(page).getByRole("tablist", { name: "Output tabs" })).toBeVisible();
    const box = await panel(page).boundingBox();
    expect(box).not.toBeNull();
    for (const tab of await panel(page).getByRole("tab").all()) {
      const b = await tab.boundingBox();
      expect(b).not.toBeNull();
      expect(b!.x).toBeGreaterThanOrEqual(box!.x);
      expect(b!.x + b!.width).toBeLessThanOrEqual(box!.x + box!.width);
      const clipped = await tab.evaluate((el) => el.scrollWidth > el.clientWidth);
      expect(clipped).toBe(false);
    }
  });
}

test("removing the last chip moves focus to the attach control", async ({ page }) => {
  await page.goto(COOMASSIE);
  await page.getByLabel("Attach files").setInputFiles([
    { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("A") },
    { name: "b.txt", mimeType: "text/plain", buffer: Buffer.from("B") },
  ]);
  await page.getByRole("button", { name: "Remove a.txt" }).click();
  await expect(page.getByRole("button", { name: "Remove b.txt" })).toBeFocused();
  await page.getByRole("button", { name: "Remove b.txt" }).click();
  await expect(page.getByLabel("Attach files")).toBeFocused();
});

test("returning to an experiment mid-build shows the work in progress", async ({ page }) => {
  await page.goto(COOMASSIE);
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
  await page.getByLabel("Attach files").setInputFiles({
    name: "reduction-protocol.txt", mimeType: "text/plain", buffer: Buffer.from("Add the reducing agent dropwise."),
  });
  await page.getByRole("textbox", { name: "Message the factory" }).fill("Here is the protocol");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Read your attachment")).toBeVisible();

  // Away to B12 and straight back, in one step so the build is still running on return.
  await page.evaluate(async ([away, back]) => {
    const heading = () => document.querySelector("main h1")?.textContent ?? "";
    const until = (text: string) => new Promise<void>((resolve) => {
      const check = () => (heading() === text ? resolve() : requestAnimationFrame(check));
      check();
    });
    window.location.hash = away;
    await until("Vitamin B12 absorbance");
    // Nothing from the other experiment shows here.
    if (document.body.innerText.includes("The factory is working")) throw new Error("working state leaked into B12");
    window.location.hash = back;
    await until("Reducing Coomassie blue");
  }, [B12.replace("/#", ""), COOMASSIE.replace("/#", "")]);
  const reply = "I added reduction-protocol.txt to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.";
  await expect(page.getByRole("status").filter({ hasText: "The factory is working…" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await expect(page.getByText("Read your attachment")).toBeVisible();
  await expect(page.getByText(reply)).toHaveCount(1, { timeout: BUILD_MS });
  await expect(page.getByText("The factory is working…")).toHaveCount(0);
  await expect(page.getByText("Rewrote procedure")).toHaveCount(1);
});

test("the B12 workspace has Procedure and Run plan tabs", async ({ page }) => {
  await page.goto(B12);
  await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
  await expect.poll(() => tabNames(page)).toEqual(["Procedure", "Run plan"]);
});
