import { expect, test } from "playwright/test";

async function chooseRun(page, runId) {
  await page.getByRole("button", { name: new RegExp(runId) }).click();
  return page.getByRole("region", { name: "Run details" });
}

test("recorded concentration and time-course fixtures retain measurements and review findings", async ({
  page,
}) => {
  await page.goto("/workspace/");
  let details = await chooseRun(page, "fixture-concentration");
  const concentrationRow = details.getByRole("row", { name: /vial-q17/ });
  await expect(
    concentrationRow.getByRole("cell", { name: "4.8", exact: true }),
  ).toBeVisible();
  await expect(
    concentrationRow.getByRole("cell", { name: "0.12", exact: true }),
  ).toBeVisible();
  await expect(
    details.getByRole("columnheader", { name: "Concentration (mg/L)" }),
  ).toBeVisible();
  for (const identity of [
    "Simulated acquisition",
    "job-101",
    "uvvis-concentration-v1",
    "6c0483ae",
    "cal-visible-01",
  ]) {
    await expect(details).toContainText(identity);
  }
  const preparation = details.getByRole("row", {
    name: /Software preparation/,
  });
  await expect(preparation.locator("time")).toHaveText([
    "2026-11-12T08:59:53Z",
    "2026-11-12T09:00:18Z",
  ]);
  await expect(
    details.getByText("Scientific review", { exact: true }),
  ).toBeVisible();
  // A reload reopens the fixture archive without submitting an acquisition.
  await page.reload();
  details = await chooseRun(page, "fixture-time-course");
  const points = details.getByRole("table", {
    name: "Recorded time-course measurements",
  });
  const first = points.getByRole("row", { name: /09:05:03Z/ });
  await expect(
    first.getByRole("cell", { name: "3 s", exact: true }),
  ).toBeVisible();
  const withheld = points.getByRole("row", { name: /09:05:35Z/ });
  await expect(
    withheld.getByRole("cell", { name: "35 s", exact: true }),
  ).toBeVisible();
  await expect(withheld.getByRole("cell", { name: "Withheld" })).toBeVisible();
  await expect(
    withheld.getByRole("cell", { name: "Unavailable" }),
  ).toBeVisible();
  await expect(withheld).toContainText("Outside calibration range");
});

test("pending preparation leaves recipe state intact and incomplete evidence has no result", async ({
  page,
}) => {
  await page.goto("/workspace/");
  const pending = await chooseRun(page, "fixture-pending");
  await expect(pending).toContainText("17 s · pending at last update");
  await expect(
    pending
      .getByRole("table", { name: "Recorded stages" })
      .getByRole("row", { name: /Acquisition/ }),
  ).toContainText("completed");
  await expect(
    pending
      .locator("dt")
      .filter({ hasText: "Acquisition recipe" })
      .locator(".."),
  ).toContainText("verified");
  const incomplete = await chooseRun(page, "fixture-interrupted");
  await expect(incomplete).toContainText("Incomplete acquisition evidence");
  await expect(
    incomplete.getByRole("table", { name: /measurements/ }),
  ).toHaveCount(0);
  const downloadPromise = page.waitForEvent("download");
  await incomplete.getByRole("button", { name: "Download evidence" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain("fixture-interrupted");
});

// Intercept only the trusted workspace API. These saved projections exercise the
// live client's wire format without implying an authenticated backend was deployed.
test("saved and replayed results preserve withheld values, independent states and release provenance", async ({
  page,
}) => {
  const stamp = "2026-11-11T17:22:03Z";
  const reasons = [
    "Invalid concentration units",
    "Nonfinite absorbance",
    "Incompatible optical settings",
    "Outside calibration range",
  ];
  const saved = {
    experiment_type: "concentration",
    run_id: "archive-A",
    job_id: "job-14",
    spec_digest: "sha-A",
    submitted_at: stamp,
    approval: "approved",
    recipe: "verified",
    software: "ready",
    acquisition: "completed",
    analysis: "completed",
    blockers: [],
    acquisition_started_at: stamp,
    acquisition_finished_at: stamp,
    software_started_at: stamp,
    software_finished_at: stamp,
    analysis_started_at: stamp,
    analysis_finished_at: stamp,
    software_wait_s: 0,
    software_wait_pending: false,
    preparation: "reuse",
    release_id: "rel-A",
    source_revision: "source-98",
    provenance: "archive",
    scientific_review: "Physical validation pending",
    result: {
      calibration_id: "cal-42",
      unit: "mg/L",
      results: reasons.map((reason, index) => ({
        sample_id: "sample-" + index,
        concentration_mg_l: null,
        replicate_sd_mg_l: null,
        review_reason: reason,
      })),
    },
  };
  const runs = [
    saved,
    {
      ...saved,
      run_id: "saved-replay",
      provenance: "replay",
      preparation: "revision",
    },
    {
      ...saved,
      run_id: "unready-build",
      preparation: "generation",
      software: "failed",
      analysis: "pending",
      software_wait_s: 117,
      software_wait_pending: true,
      release_id: null,
      source_revision: null,
      result: null,
      blockers: [
        "Calibration requires project approval",
        "Build failed verification",
      ],
    },
    // Ensure retained evidence cannot become a completed result, even when the
    // service sends result rows alongside a terminal incomplete acquisition.
    ...["partial", "cancelled", "interrupted"].map((acquisition) => ({
      ...saved,
      run_id: "incomplete-" + acquisition,
      acquisition,
      software_wait_s: null,
    })),
  ];
  await page.route(
    "**/v1/projects/test-scope/workspace?project_id=test-scope",
    (route) =>
      route.fulfill({
        json: {
          project_id: "test-scope",
          recorded_at: stamp,
          labs: [],
          projects: [],
          calibrations: [],
          specifications: [],
          runs,
        },
      }),
  );
  await page.goto("/workspace/?mode=live&project=test-scope");
  const details = await chooseRun(page, "archive-A");
  for (const expected of [
    "Archived run",
    "rel-A",
    "source-98",
    "reuse",
    "cal-42",
    "Physical validation pending",
  ]) {
    await expect(details).toContainText(expected);
  }
  for (const reason of reasons) {
    const row = details.getByRole("row").filter({ hasText: reason });
    await expect(
      row.getByRole("cell", { name: "Withheld", exact: true }),
    ).toBeVisible();
    await expect(
      row.getByRole("cell", { name: "Unavailable", exact: true }),
    ).toBeVisible();
  }
  await chooseRun(page, "saved-replay");
  await expect(details).toContainText("Replay of saved measurements");
  await expect(details.getByText("revision", { exact: true })).toBeVisible();
  await chooseRun(page, "unready-build");
  for (const expected of [
    "verified",
    "generation",
    "failed",
    "117 s · pending",
    ...runs[2].blockers,
  ]) {
    await expect(details).toContainText(expected);
  }
  await expect(details).toContainText("Not available");
  for (const state of ["partial", "cancelled", "interrupted"]) {
    await chooseRun(page, "incomplete-" + state);
    await expect(details).toContainText("Incomplete acquisition evidence");
    await expect(
      details.getByRole("table", { name: /measurements/ }),
    ).toHaveCount(0);
    await expect(
      details
        .locator("dt")
        .filter({ hasText: "Software-induced wait" })
        .locator(".."),
    ).toContainText("Not recorded");
  }
});
