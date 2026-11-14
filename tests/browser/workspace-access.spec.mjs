import { test, expect } from "playwright/test";

async function response(page, value) {
  const select = page.getByLabel("Response to next requests");
  if (!(await select.isVisible()))
    await page.getByText("Fixture controls", { exact: true }).click();
  await select.selectOption(value);
}

for (const [fault, message] of [
  ["unauthenticated", "Authentication required"],
  ["expired", "Session expired"],
  ["forbidden", "Access denied"],
])
  for (const trigger of [
    "Refresh workspace",
    "Save lab revision",
    "Download evidence",
  ]) {
    test(`${fault} ${trigger} clears project records and drafts`, async ({
      page,
    }) => {
      await page.goto("/workspace/");
      await expect(
        page.getByRole("region", { name: "Run details" }),
      ).toContainText("job-101");
      if (trigger === "Save lab revision")
        await page.getByRole("button", { name: "Lab & project" }).click();
      await response(page, fault);
      await page.getByRole("button", { name: trigger, exact: true }).click();
      await expect(page.getByRole("main").getByRole("alert")).toContainText(
        message,
      );
      await expect(page.getByText("job-101", { exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Lab name", { exact: true })).toHaveCount(0);
    });
  }

test("a failed poll freezes server timing and a successful poll clears stale status", async ({
  page,
}) => {
  await page.clock.install();
  await page.goto("/workspace/");
  await page.getByRole("button", { name: /fixture-pending/ }).click();
  const details = page.getByRole("region", { name: "Run details" });
  await expect(details).toContainText("17 s · pending");
  await response(page, "unavailable");
  await page.clock.fastForward(30000);
  await expect(
    page.getByRole("status").filter({ hasText: "Stale progress" }),
  ).toContainText("2026-11-12T09:10:47Z");
  await expect(details).toContainText("17 s · pending");
  await expect(details).toContainText(
    "Waiting for a compatible verified release",
  );
  await response(page, "");
  await page.clock.fastForward(12000);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expect(details).toContainText("Recorded snapshot");
});

test("project switches discard private drafts, session end clears demo revisions", async ({
  page,
}) => {
  await page.goto("/workspace/");
  await page.getByRole("button", { name: "Lab & project" }).click();
  await page.getByLabel("Lab name", { exact: true }).fill("Edited demo lab");
  await page.getByRole("button", { name: "Save lab revision" }).click();
  await expect(
    page.getByText("Saved lab revision 2.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Lab name", { exact: true })
    .fill("Unsaved private draft");
  await page.getByLabel("Fixture project").selectOption("foreign-project");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Access denied",
  );
  await page.getByLabel("Fixture project").selectOption("empty-assay");
  await expect(
    page.getByRole("heading", { name: "Create your first experiment" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New specification" }).click();
  await expect(
    page.getByLabel("Sample IDs (one per line)", { exact: true }),
  ).toHaveValue("");
  await page.getByLabel("Fixture project").selectOption("visible-assay");
  await page.getByRole("button", { name: "Lab & project" }).click();
  await expect(page.getByLabel("Lab name", { exact: true })).toHaveValue(
    "Edited demo lab",
  );
  await page.getByRole("button", { name: "End session" }).click();
  await expect(page.getByText("job-101", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Reopen workspace" }).click();
  await page.getByRole("button", { name: "Lab & project" }).click();
  await expect(page.getByLabel("Lab name", { exact: true })).toHaveValue(
    "Demonstration Optics Lab",
  );
});

test("live transport discards late responses after changing scope and never falls back to fixtures", async ({
  page,
}) => {
  let respond, started;
  const requested = new Promise((resolve) => {
    started = resolve;
  });
  const delayed = new Promise((resolve) => {
    respond = resolve;
  });
  await page.route("**/v1/projects/first/workspace?*", async (route) => {
    started();
    await delayed;
    await route.fulfill({
      json: {
        project_id: "first",
        recorded_at: "first scope record",
        runs: [],
        specifications: [],
        labs: [],
        projects: [],
        calibrations: [],
      },
    });
  });
  await page.route("**/v1/projects/second/workspace?*", (route) =>
    route.fulfill({
      status: 403,
      json: {
        message: "Private finding for another member",
        fields: { sample_id: "protected sample XY" },
      },
    }),
  );
  await page.goto("/workspace/?mode=live&project=first");
  await requested;
  await expect(page.getByText("Loading workspace…")).toBeVisible();
  await page.getByLabel("Project ID", { exact: true }).fill("second");
  await page.getByRole("button", { name: "Open project" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Access denied",
  );
  respond();
  await expect(
    page.getByRole("heading", { name: "Create your first experiment" }),
  ).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(
    /Private finding|protected sample XY|job-101/,
  );
  await page.route("**/v1/projects/third/workspace?*", (route) =>
    route.fulfill({ status: 503, body: "service offline" }),
  );
  await page.getByLabel("Project ID", { exact: true }).fill("third");
  await page.getByRole("button", { name: "Open project" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Live execution unavailable",
  );
  await expect(page.getByRole("region", { name: "Run details" })).toHaveCount(
    0,
  );
});

test("the workspace and both saved archives remain navigable", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Researcher workspace" }).click();
  await page.getByRole("link", { name: "B12 archive" }).click();
  await expect(
    page.getByRole("heading", { name: "Vitamin B12 assay" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "EPR workbench" }).click();
  await expect(
    page.getByRole("button", { name: "Run work order" }),
  ).toBeVisible();
  await page.goto("/workspace/");
  await page.getByRole("link", { name: "EPR archive" }).click();
  await expect(
    page.getByRole("button", { name: "Run work order" }),
  ).toBeVisible();
});

test("live evidence is fetched through the scoped API and denied evidence never downloads", async ({
  page,
}) => {
  const id = "evidence-check";
  await page.goto("/workspace/");
  await expect(page.getByText("job-101", { exact: true })).toBeVisible();
  const snapshot = await page.evaluate(
    () =>
      JSON.parse(
        sessionStorage.getItem("evolve.workspace.fixture.v2/visible-assay"),
      ).snapshot,
  );
  const calls = [];
  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("project_id")).toBe(id);
    if (url.pathname === "/v1/projects/" + id + "/workspace")
      return route.fulfill({ json: { ...snapshot, project_id: id } });
    calls.push(url.pathname);
    if (calls.length === 1)
      return route.fulfill({
        contentType: "application/zip",
        body: "authorized bundle bytes",
      });
    if (calls.length === 2)
      return route.fulfill({ status: 200, contentType: "application/zip", body: "" });
    return route.fulfill({
      status: 401,
      json: { code: "expired_session", message: "hidden report" },
    });
  });
  await page.goto("/workspace/?mode=live&project=" + id);
  const evidence = page.getByRole("button", { name: "Download evidence" });
  const downloaded = page.waitForEvent("download");
  await evidence.click();
  const file = await downloaded;
  const chunks = [];
  for await (const chunk of await file.createReadStream()) chunks.push(chunk);
  expect(Buffer.concat(chunks).toString()).toBe("authorized bundle bytes");
  await evidence.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("invalid response");
  await evidence.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Session expired",
  );
  await expect(page.locator("body")).not.toContainText(/job-101|hidden report/);
  expect(calls).toEqual(
    Array(3).fill("/v1/runs/fixture-concentration/evidence"),
  );
});

test("workspace identifies the source commit and isolates live access in preview builds", async ({ page }) => {
  const preview = process.env.VERCEL_ENV === "preview";
  const requests = [];
  await page.route("**/v1/**", (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 503 });
  });
  await page.goto(preview ? "/workspace/?mode=live&project=source-check" : "/workspace/");
  const commit = page.getByText(/^Preview commit /);
  if (preview) {
    await expect(commit).toHaveText("Preview commit " + (process.env.VERCEL_GIT_COMMIT_SHA || "unavailable"));
    await expect(page.getByLabel("Data source").locator('option[value="live"]')).toBeDisabled();
    await expect(page.getByText("Live access is unavailable in this preview.")).toBeVisible();
    await page.getByLabel("Data source").selectOption("fixture");
  } else {
    await expect(commit).toHaveCount(0);
  }
  await expect(page.getByRole("heading", { name: "Experiment runs" })).toBeVisible();
  expect(requests).toEqual([]);
});
