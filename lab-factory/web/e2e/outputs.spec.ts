import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, goto } from "./helpers.ts";

const PROCEDURE_LINE =
  "Only settings shown on a range are checked against your instruments. The rest is written for you and your approver to judge.";

function tabBody(page: Page, name: string) {
  return page.getByRole("region", { name: "Outputs" }).getByRole("tabpanel", { name });
}

async function openTab(page: Page, name: string) {
  const tab = page.getByRole("region", { name: "Outputs" }).getByRole("tab", { name });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return tabBody(page, name);
}

/** The numbered steps of a procedure or run plan, one list item each. */
function steps(body: ReturnType<typeof tabBody>) {
  return body.getByRole("list", { name: "Steps" }).getByRole("listitem");
}

test.describe("the Coomassie procedure", () => {
  test.beforeEach(async ({ page }) => {
    await goto(page, COOMASSIE);
    await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
  });

  test("says what is checked, once, above the steps", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    await expect(body.getByText(PROCEDURE_LINE, { exact: true })).toHaveCount(1);
    await expect(body.getByRole("list", { name: "Steps" })).toBeVisible();
    await expect(steps(body)).toHaveCount(5);
  });

  test("shows the submission summary and the status", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();
    await expect(body.getByText("Being revised", { exact: true })).toBeVisible();
  });

  test("shows step 2's wavelength on its range", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const step2 = steps(body).nth(1);
    await expect(step2).toContainText("Blank the spectrophotometer with solvent only.");
    const strip = step2.getByRole("img", { name: "Wavelength 595 nm, allowed 400 to 700 nm" });
    await expect(strip).toBeVisible();
    await expect(strip.locator(".range-marker")).toHaveAttribute("style", /left: 65%/);
  });

  test("labels the amount as not checked, and only once", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const label = body.getByText("Not checked: dye solution 1 mL", { exact: true });
    await expect(label).toHaveCount(1);
    await expect(steps(body).nth(0)).toContainText("Not checked: dye solution 1 mL");
  });

  test("shows the failing citation check on step 4", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const step4 = steps(body).nth(3);
    await expect(step4).toContainText("Add the reducing agent and mix.");
    const note = step4.getByRole("note");
    await expect(note).toHaveText("step 4: citations: no citation");
    await expect(step4.getByRole("link")).toHaveCount(0);
    // The only failure in the procedure is that one.
    await expect(body.getByRole("note")).toHaveCount(1);
  });

  test("a source opens the document drawer", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    const source = steps(body).nth(0).getByRole("link", { name: "Dye stock preparation" });
    await expect(source).toHaveAttribute("href", /doc=coomassie-dye-prep/);
    await source.click();
    const drawer = page.getByRole("complementary", { name: "Document" });
    await expect(drawer.getByRole("heading", { level: 2, name: "Dye stock preparation" })).toBeVisible();
    await expect(page).toHaveURL(/experiments\/coomassie-run-1\?doc=coomassie-dye-prep$/);
  });
});

test.describe("the B12 outputs", () => {
  test.beforeEach(async ({ page }) => {
    await goto(page, B12);
    await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
  });

  test("the procedure passed and waits for sign-off", async ({ page }) => {
    const body = tabBody(page, "Procedure");
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, all checks passed" })).toBeVisible();
    await expect(body.getByText("Waiting for sign-off", { exact: true })).toBeVisible();
    await expect(body.getByRole("note")).toHaveCount(0);
    await expect(body.getByText("Not checked: sample 1 mL", { exact: true })).toBeVisible();
  });

  test("the run plan shows the command line, the out-of-range marker and the failing check", async ({ page }) => {
    const body = await openTab(page, "Run plan");
    await expect(body.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();
    await expect(body.getByText("Being revised", { exact: true })).toBeVisible();

    const step1 = steps(body).nth(0);
    // Two spaces between the instrument and the command, kept as written.
    const command = step1.getByText("uvvis-1  read_absorbance", { exact: true });
    await expect(command).toBeVisible();
    expect(await command.textContent()).toBe("uvvis-1  read_absorbance");
    expect(await command.evaluate((el) => (el as HTMLElement).innerText)).toBe("uvvis-1  read_absorbance");

    const strip = step1.getByRole("img", { name: "Wavelength 750 nm, allowed 400 to 700 nm" });
    await expect(strip).toBeVisible();
    const left = await strip.locator(".range-marker").evaluate((el) => (el as HTMLElement).style.left);
    expect(left).toBe("100%");

    await expect(step1.getByRole("note")).toHaveText("step 1: wavelength: 750 nm is above the maximum 700 nm");
  });

  test("sending to an instrument is disabled and says why", async ({ page }) => {
    const body = await openTab(page, "Run plan");
    const send = body.getByRole("button", { name: "Send to instrument" });
    await expect(send).toBeDisabled();
    await expect(send).toHaveAccessibleDescription("Instruments are controlled by the instrument agent, which comes later.");
  });
});

const PROTOCOL_REPLY = "I added reduction-protocol.txt to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.";

/** Attaches the reduction protocol on Coomassie and waits for the rewritten procedure, which cites it on step 4. */
async function attachProtocol(page: Page) {
  await page.getByLabel("Attach files").setInputFiles({
    name: "reduction-protocol.txt", mimeType: "text/plain", buffer: Buffer.from("Add the reducing agent dropwise."),
  });
  await page.getByRole("textbox", { name: "Message the factory" }).fill("Here is the protocol");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(PROTOCOL_REPLY)).toHaveCount(1, { timeout: 20_000 });
}

type Box = { x: number; y: number; width: number; height: number };
const intersects = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

for (const width of [1440, 1100]) {
  test(`sources sit after the step text, inside the panel, at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await goto(page, COOMASSIE);
    await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
    await attachProtocol(page);
    const body = tabBody(page, "Procedure");
    await expect(steps(body).nth(3).getByRole("link", { name: "reduction-protocol.txt" })).toBeVisible();

    const links = await body.getByRole("list", { name: "Steps" }).getByRole("link").all();
    expect(links.length).toBeGreaterThanOrEqual(5);
    const panelBox = await body.boundingBox();
    expect(panelBox).not.toBeNull();
    for (const link of links) {
      // A real space separates a source from the words before it, so the two never run together.
      const before = await link.evaluate((el) => {
        const range = document.createRange();
        range.setStart(el.closest("p")!, 0);
        range.setEndBefore(el);
        return range.toString();
      });
      expect(before).toMatch(/\S\s+$/);
      const box = await link.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(panelBox!.x);
      expect(box!.x + box!.width).toBeLessThanOrEqual(panelBox!.x + panelBox!.width);
    }
    const overflow = await body.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

for (const [name, url] of [["Coomassie", COOMASSIE], ["B12", B12]] as const) {
  test(`every source on ${name} has its own hit area of at least 40 px`, async ({ page }) => {
    await goto(page, url);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const body = tabBody(page, "Procedure");
    await expect(steps(body).first()).toBeVisible();
    const links = await body.getByRole("list", { name: "Steps" }).getByRole("link").all();
    expect(links.length).toBeGreaterThan(0);
    const boxes: Box[] = [];
    for (const link of links) {
      // The link itself receives a click at its centre: nothing else lies over it.
      await link.scrollIntoViewIfNeeded();
      const hit = await link.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return top !== null && el.contains(top);
      });
      expect(hit).toBe(true);
    }
    // Measured in one go, so every box shares the same scroll position.
    const rects = await body.getByRole("list", { name: "Steps" }).getByRole("link").evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.left, y: r.top, width: r.width, height: r.height };
      }));
    for (const box of rects) {
      expect(box.height).toBeGreaterThanOrEqual(40);
      boxes.push(box);
    }
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) expect(intersects(boxes[i], boxes[j])).toBe(false);
    }
  });
}
