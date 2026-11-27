import { expect, test } from "playwright/test";
import { goto } from "./helpers.ts";

test("the research and sample skills are listed with their enabled state", async ({ page }) => {
  await goto(page, "/#/skills");
  await expect(page.getByRole("heading", { name: "Skills", level: 1 })).toBeVisible();
  await expect(page.getByText("Instructions every agent follows when it works for this lab.")).toBeVisible();
  await expect(page.getByText("Skills that are switched on are followed every time the factory builds.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Skills" }).getByRole("listitem")).toHaveCount(14);
  await expect(page.getByRole("switch", { name: "Claim-to-evidence review enabled" })).toHaveAttribute("aria-checked", "false");
  const plotting = page.getByRole("switch", { name: "Plotting conventions enabled" });
  await expect(plotting).toHaveAttribute("aria-checked", "false");
  await expect(page.getByRole("switch", { name: "How we write procedures enabled" })).toHaveAttribute("aria-checked", "true");

  await plotting.click();
  await expect(plotting).toHaveAttribute("aria-checked", "true");

  await goto(page, "/#/connectors");
  await expect(page.getByRole("heading", { name: "Connectors", level: 1 })).toBeVisible();
  await goto(page, "/#/skills");
  await expect(page.getByRole("switch", { name: "Plotting conventions enabled" })).toHaveAttribute("aria-checked", "true");
});

async function createSkill(page: import("playwright/test").Page, title: string, description = "") {
  await goto(page, "/#/skills?skill=new");
  await page.getByLabel("Title").fill(title);
  if (description) await page.getByLabel("Description").fill(description);
  await page.getByLabel("Instructions (Markdown)").fill("- Be brief.");
  await page.getByRole("button", { name: "Save skill" }).click();
}

test("a skill titled New does not collide with the new-skill route", async ({ page }) => {
  await createSkill(page, "New");
  await expect(page.getByText("Saved as revision 1")).toBeVisible();
  await expect(page).toHaveURL(/#\/skills\?skill=new-2$/);
  await expect(page.getByRole("heading", { name: "Edit skill", level: 2 })).toBeVisible();
  await page.getByText("Revision history").click();
  await expect(page.getByRole("list", { name: "Revisions" }).getByRole("listitem")).toHaveCount(1);
});

test("a long unbroken skill title does not widen the page", async ({ page }) => {
  await createSkill(page, "x".repeat(300), "y".repeat(300));
  await expect(page.getByText("Saved as revision 1")).toBeVisible();
  await goto(page, "/#/skills");
  await expect(page.getByRole("list", { name: "Skills" }).getByRole("listitem")).toHaveCount(15);
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(await fits()).toBe(true);
  await page.setViewportSize({ width: 390, height: 800 });
  expect(await fits()).toBe(true);
});

test("a new skill is saved as revision 1, then edited into revision 2", async ({ page }) => {
  await goto(page, "/#/skills");
  await page.getByRole("link", { name: "New skill" }).click();
  await expect(page).toHaveURL(/#\/skills\?skill=new$/);
  await expect(page.getByRole("heading", { name: "New skill", level: 2 })).toBeVisible();
  const save = page.getByRole("button", { name: "Save skill" });
  await expect(save).toBeDisabled();

  await page.getByLabel("Title").fill("Error bars");
  await page.getByLabel("Description").fill("Show the spread of repeated readings.");
  await page.getByLabel("Instructions (Markdown)").fill("- Draw error bars as one standard deviation.");
  await expect(page.getByRole("region", { name: "Preview of the instructions" })).toContainText("one standard deviation");
  await save.click();
  await expect(page.getByText("Saved as revision 1")).toBeVisible();
  await expect(page).toHaveURL(/#\/skills\?skill=error-bars$/);
  await expect(page.getByRole("heading", { name: "Edit skill", level: 2 })).toBeVisible();
  await expect(page.getByText("Saved as revision 1")).toBeVisible();
  await expect(page.getByRole("list", { name: "Skills" }).getByRole("listitem")).toHaveCount(15);

  await save.click();
  await expect(page.getByText("No changes to save.")).toBeVisible();

  await page.getByLabel("Instructions (Markdown)").fill("- Draw error bars as one standard error.");
  await expect(page.getByText("No changes to save.")).toHaveCount(0);
  await save.click();
  await expect(page.getByText("Saved as revision 2")).toBeVisible();
  await page.getByText("Revision history").click();
  await expect(page.getByRole("list", { name: "Revisions" }).getByRole("listitem")).toHaveCount(2);

  await page.getByRole("link", { name: "Close" }).click();
  await expect(page).toHaveURL(/#\/skills$/);
  await expect(page.getByRole("heading", { name: "Edit skill" })).toHaveCount(0);
});

test("an unknown skill says it isn't in this lab", async ({ page }) => {
  await goto(page, "/#/skills?skill=nope");
  await expect(page.getByText("That skill doesn't exist in this lab.")).toBeVisible();
});

test("Zotero is connected, and its item can be added to a project", async ({ page }) => {
  await goto(page, "/#/connectors");
  await expect(page.getByRole("heading", { name: "Connectors", level: 1 })).toBeVisible();
  await expect(page.getByText("Connections here are simulated.")).toBeVisible();
  const zotero = page.getByRole("region", { name: "Zotero" });
  await expect(zotero.getByText("Connected as Emory Biophysics library")).toBeVisible();
  await expect(zotero.getByText("Papers", { exact: true })).toBeVisible();

  // Connected connectors come first.
  await expect(page.getByRole("main").getByRole("heading", { level: 2 }).first()).toHaveText("Zotero");

  const title = "Reduction of triarylmethane dyes (sample)";
  const select = zotero.getByRole("combobox", { name: `Add to, ${title}` });
  await expect(select.locator("optgroup")).toHaveCount(2);
  await select.selectOption({ label: "Project: Coomassie reduction" });
  await zotero.getByRole("button", { name: `Add ${title}` }).click();
  await expect(zotero.getByText(/^Added to Coomassie reduction as revision \d+$/)).toBeVisible();

  await goto(page, "/#/projects/coomassie-reduction");
  const aside = page.getByRole("complementary", { name: "Shared with every experiment in this project" });
  await expect(aside.getByRole("link", { name: title })).toBeVisible();
});

test("Google Drive can be connected under a name, then disconnected", async ({ page }) => {
  await goto(page, "/#/connectors");
  const drive = page.getByRole("region", { name: "Google Drive" });
  await expect(drive.getByText("Not connected")).toBeVisible();
  await expect(drive.getByText("Coomassie dye protocol (sample)")).toHaveCount(0);

  await drive.getByRole("button", { name: "Connect Google Drive" }).click();
  const connect = drive.getByRole("button", { name: "Connect Google Drive" });
  await expect(connect).toBeDisabled();
  await drive.getByLabel("Account or folder name").fill("Lab drive");
  await connect.click();
  await expect(drive.getByText("Connected as Lab drive")).toBeVisible();
  await expect(drive.getByText("Coomassie dye protocol (sample)")).toBeVisible();

  await drive.getByRole("button", { name: "Disconnect Google Drive" }).click();
  await expect(drive.getByText("Not connected")).toBeVisible();
});

test("a readings item points to the Results tab, and Cancel closes the connect field", async ({ page }) => {
  await goto(page, "/#/connectors");
  const folder = page.getByRole("region", { name: "Instrument data folder" });
  await expect(folder.getByText("Connected as uvvis-1 exports")).toBeVisible();
  await expect(folder.getByText("Available in the Results tab.")).toBeVisible();
  await expect(folder.getByRole("button", { name: /^Add / })).toHaveCount(0);

  const drive = page.getByRole("region", { name: "Google Drive" });
  await drive.getByRole("button", { name: "Connect Google Drive" }).click();
  await drive.getByRole("button", { name: "Cancel" }).click();
  await expect(drive.getByLabel("Account or folder name")).toHaveCount(0);
});

test("the agent page shows the MCP setup, the skill download and connected agents", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await goto(page, "/#/agents");
  await expect(page.getByRole("heading", { name: "Connect your agent", level: 1 })).toBeVisible();
  for (const name of ["Via MCP", "As a skill", "Connected agents", "What agents can and can't do"]) {
    await expect(page.getByRole("heading", { name, level: 2 })).toBeVisible();
  }

  const claude = page.getByRole("region", { name: "Claude Code" });
  await expect(claude).toContainText("claude mcp add labfactory");
  await expect(page.getByRole("region", { name: "Codex (~/.codex/config.toml)" })).toContainText("[mcp_servers.labfactory]");
  await expect(page.getByRole("region", { name: "Cursor (.cursor/mcp.json)" })).toContainText("mcpServers");
  await expect(page.getByText("Use absolute paths to your Lab Factory checkout and your lab's database.")).toBeVisible();

  const table = page.getByRole("table", { name: "MCP tools" });
  await expect(table.getByRole("columnheader", { name: "Tool" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "What it does" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "submit_artifact" })).toBeVisible();
  await expect(table.getByRole("row")).toHaveCount(5);

  await page.getByRole("button", { name: "Copy Claude Code" }).click();
  await expect(page.getByText("Copied", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("claude mcp add labfactory");

  const download = page.getByRole("link", { name: "Download SKILL.md" });
  await expect(download).toHaveAttribute("href", "/skills/labfactory-work-orders/SKILL.md");
  await expect(download).toHaveAttribute("download", "SKILL.md");
  const response = await page.request.get("/skills/labfactory-work-orders/SKILL.md");
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain("labfactory-work-orders");

  await page.getByText("Show SKILL.md").click();
  await expect(page.getByRole("region", { name: "SKILL.md" })).toContainText("Working Lab Factory work orders");

  const connected = page.getByRole("region", { name: "Connected agents" });
  await expect(connected.getByText("codex on lab-pc")).toBeVisible();
  const codex = connected.getByRole("listitem").filter({ hasText: "codex on lab-pc" });
  await expect(codex.getByText(/^Last seen \d{1,2} \w{3} \d{4}$/)).toBeVisible();
  await expect(codex.getByRole("link", { name: "WO-B12", exact: true })).toHaveAttribute("href", /#\/projects\/.+\/experiments\/.+/);
  await expect(page.getByText("Agents can claim work and submit it for checks. Only a person can sign off a submission.")).toBeVisible();
});

test("copying says so when the clipboard refuses", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: () => Promise.reject(new Error("denied")) },
    });
  });
  await goto(page, "/#/agents");
  await page.getByRole("button", { name: "Copy Claude Code" }).click();
  await expect(page.getByText("Couldn't copy. Select the text and copy it yourself.")).toBeVisible();
});

test("Ctrl+K, plot and Enter open the Plotting conventions editor", async ({ page }) => {
  await goto(page, "/");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Search the lab" }).fill("plot");
  await expect(dialog.getByRole("option", { name: /Plotting conventions/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/skills\?skill=plot-style$/);
  await expect(page.getByRole("heading", { name: "Edit skill", level: 2 })).toBeVisible();
  await expect(page.getByLabel("Title")).toHaveValue("Plotting conventions");
});
