import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "playwright/test";
import type { Page } from "playwright/test";

import { B12, COOMASSIE, attachProtocol, startExperiment, viewAs, goto } from "./helpers.ts";

// Pyodide loads in the worker on the first run, so the first computed result gets a long wait.
const COMPUTE = { timeout: 80_000 };

type Screen = {
  name: string;
  prepare: (page: Page) => Promise<void>;
};

function panel(page: Page) {
  return page.getByRole("region", { name: "Outputs" });
}

async function openTab(page: Page, name: string) {
  const tab = panel(page).getByRole("tab", { name, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return panel(page).getByRole("tabpanel", { name, exact: true });
}

async function openCoomassie(page: Page) {
  await goto(page, COOMASSIE);
  await expect(page.getByRole("heading", { level: 1, name: "Reducing Coomassie blue" })).toBeVisible();
}

async function openB12(page: Page) {
  await goto(page, B12);
  await expect(page.getByRole("heading", { level: 1, name: "Vitamin B12 absorbance" })).toBeVisible();
}

/** The lab home with its attention list loaded: items, or the line that says there are none. */
async function homeLoaded(page: Page) {
  const attention = page.getByRole("region", { name: "Needs your attention" });
  await expect(attention.getByRole("link").first().or(attention.getByText("Nothing needs you right now."))).toBeVisible();
}

/** The screens, each reached the way a person would reach it. Every one runs in both themes. */
const SCREENS: Screen[] = [
  { name: "lab home", prepare: async (page) => { await goto(page, "/#/"); await homeLoaded(page); } },
  {
    name: "lab home as approver",
    prepare: async (page) => {
      await goto(page, "/#/");
      await homeLoaded(page);
      await viewAs(page, "Approver");
      const attention = page.getByRole("region", { name: "Needs your attention" });
      await expect(attention.getByText("Waiting for sign-off").first()).toBeVisible();
    },
  },
  {
    name: "lab page",
    prepare: async (page) => {
      await goto(page, "/#/lab");
      await expect(page.getByText("Revision history")).toBeVisible();
      await expect(page.locator(".range-strip").first()).toBeVisible();
    },
  },
  {
    name: "lab settings",
    prepare: async (page) => {
      await goto(page, "/#/settings");
      await expect(page.getByRole("radio", { name: "Anyone who gives their name" })).toBeEnabled();
      await expect(page.getByRole("radio", { checked: true })).toHaveCount(1);
    },
  },
  {
    name: "skills with the editor open",
    prepare: async (page) => {
      await goto(page, "/#/skills?skill=procedure-style");
      const form = page.getByRole("form", { name: "Edit skill" });
      await expect(form.getByLabel("Title")).not.toHaveValue("");
      await expect(form.getByLabel("Instructions (Markdown)")).not.toHaveValue("");
    },
  },
  {
    name: "connectors",
    prepare: async (page) => {
      await goto(page, "/#/connectors");
      await expect(page.getByText("Connected as Emory Biophysics library")).toBeVisible();
    },
  },
  {
    name: "connect your agent",
    prepare: async (page) => {
      await goto(page, "/#/agents");
      const agents = page.getByRole("region", { name: "Connected agents" });
      await expect(agents.getByText("codex on lab-pc", { exact: true })).toBeVisible();
    },
  },
  {
    name: "Coomassie project page",
    prepare: async (page) => {
      await goto(page, "/#/projects/coomassie-reduction");
      const aside = page.getByRole("complementary", { name: "Shared with every experiment in this project" });
      await expect(aside.getByRole("link").first()).toBeVisible();
    },
  },
  {
    name: "not found",
    prepare: async (page) => {
      await goto(page, "/#/projects/nope/experiments/nothing");
      await expect(page.getByRole("link", { name: "Go to lab home" })).toBeVisible();
    },
  },
  {
    name: "experiment context open",
    prepare: async (page) => {
      await openCoomassie(page);
      await page.getByRole("button", { name: "Experiment context" }).click();
      const section = page.getByRole("region", { name: "Experiment context" });
      await expect(section.getByRole("heading", { name: "Instruments" })).toBeVisible();
      await expect(section.getByText("Loading")).toHaveCount(0);
    },
  },
  {
    name: "Coomassie workspace, Procedure tab",
    prepare: async (page) => {
      await openCoomassie(page);
      const body = await openTab(page, "Procedure");
      await expect(body.getByRole("heading", { level: 2, name: "Submission 1, 1 check failed" })).toBeVisible();
    },
  },
  {
    name: "Coomassie workspace, Analysis app tab",
    prepare: async (page) => {
      await openCoomassie(page);
      const body = await openTab(page, "Analysis app");
      await expect(body.locator("tbody tr").filter({ hasText: "Passed" })).toHaveCount(3, COMPUTE);
    },
  },
  {
    name: "Coomassie workspace, Results tab",
    prepare: async (page) => {
      await openCoomassie(page);
      const body = await openTab(page, "Results");
      const folder = body.getByRole("region", { name: "From your instrument data folder" });
      await folder.getByRole("button", { name: "Analyze coomassie-run-1.csv" }).click();
      await expect(body.getByRole("list", { name: "Analysis results" })).toBeVisible(COMPUTE);
      await expect(body.getByRole("img", { name: /^Readings and fit\./ })).toBeVisible();
    },
  },
  {
    name: "Coomassie workspace, Simulation tab",
    prepare: async (page) => {
      await openCoomassie(page);
      const body = await openTab(page, "Simulation");
      await body.getByRole("button", { name: "Run simulation" }).click();
      await expect(body.getByRole("img", { name: /^Fading curves/ })).toBeVisible(COMPUTE);
      await expect(body.getByRole("status").filter({ hasText: "Simulation" })).toHaveText("Simulation done.");
    },
  },
  {
    name: "B12 workspace, Run plan tab",
    prepare: async (page) => {
      await openB12(page);
      const body = await openTab(page, "Run plan");
      await expect(body.getByRole("button", { name: "Send to instrument" })).toBeVisible();
    },
  },
  {
    name: "command palette with results",
    prepare: async (page) => {
      await goto(page, "/#/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.keyboard.press("Control+k");
      const input = page.getByRole("combobox", { name: "Search the lab" });
      await expect(input).toBeFocused();
      await input.fill("b12");
      await expect(page.getByRole("dialog").getByRole("option", { name: /B12 quantification/ })).toBeVisible();
    },
  },
  {
    name: "document drawer open",
    prepare: async (page) => {
      await goto(page, "/#/projects/coomassie-reduction/experiments/coomassie-run-1?doc=coomassie-dye-prep");
      const drawer = page.getByRole("complementary", { name: "Document" });
      await expect(drawer.getByRole("heading", { level: 2, name: "Dye stock preparation" })).toBeVisible();
    },
  },
  {
    name: "lab menu open",
    prepare: async (page) => {
      await goto(page, "/#/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.getByRole("navigation", { name: "Lab" }).getByRole("button", { name: /Emory Biophysics/ }).click();
      await expect(page.getByRole("radio", { name: "Approver" })).toBeVisible();
    },
  },
  {
    name: "new experiment proposal card",
    prepare: async (page) => {
      await startExperiment(page, "Measure how fast a dye fades");
      await expect(page.getByRole("list", { name: "Conversation" })).toBeVisible();
    },
  },
  {
    name: "comparison and Built from open",
    prepare: async (page) => {
      await openCoomassie(page);
      await attachProtocol(page);
      const body = panel(page).getByRole("tabpanel", { name: "Procedure" });
      await body.getByRole("button", { name: "Compare" }).click();
      await expect(body.getByRole("list", { name: "Changes" })).toBeVisible();
      const built = body.locator("details", { has: page.getByText("Built from", { exact: true }) });
      await built.getByText("Built from", { exact: true }).click();
      await expect(built).toHaveAttribute("open", "");
    },
  },
  {
    name: "approver's sign-off form open",
    prepare: async (page) => {
      await openB12(page);
      await viewAs(page, "Approver");
      const body = panel(page).getByRole("tabpanel", { name: "Procedure" });
      await body.getByRole("button", { name: "Approve submission 1", exact: true }).click();
      await expect(body.getByLabel("Your name")).toBeVisible();
    },
  },
];

const THEMES = ["light", "dark"] as const;

function describeViolations(violations: Awaited<ReturnType<AxeBuilder["analyze"]>>["violations"]): string {
  return violations
    .map((v) => {
      const nodes = v.nodes.map((n) => `    ${n.target.join(" ")}\n      ${n.failureSummary?.replace(/\n/g, "\n      ") ?? ""}`).join("\n");
      return `${v.id} (${v.impact}): ${v.help}\n${nodes}`;
    })
    .join("\n\n");
}

for (const theme of THEMES) {
  test.describe(`accessibility, ${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => window.localStorage.setItem("labfactory.theme", value), theme);
    });

    for (const screen of SCREENS) {
      test(`${screen.name} has no axe violations`, async ({ page }) => {
        test.setTimeout(90_000);
        await screen.prepare(page);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
        expect(results.passes.length, "axe should have checked the page").toBeGreaterThan(5);
        expect(results.violations.length, describeViolations(results.violations)).toBe(0);
      });
    }
  });
}
