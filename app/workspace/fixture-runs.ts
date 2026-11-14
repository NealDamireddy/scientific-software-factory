// Recorded sample responses. These times and scientific outputs are intentionally
// literal: polling the fixture cannot advance a job or recalculate a result.
import type { Run, Specification } from "./api";

export function queuedRun(run_id: string, spec: Specification, submitted_at: string): Run {
  return {
    run_id,
    spec_digest: spec.sha256,
    experiment_type: spec.experiment_type,
    submitted_at,
    job_id: null,
    approval: "approved",
    recipe: "pending",
    software: "pending",
    acquisition: "queued",
    analysis: "pending",
    blockers: ["Awaiting readiness check"],
    software_started_at: null,
    software_finished_at: null,
    acquisition_started_at: null,
    acquisition_finished_at: null,
    analysis_started_at: null,
    analysis_finished_at: null,
    software_wait_s: null,
    software_wait_pending: false,
    preparation: null,
    release_id: null,
    source_revision: null,
    provenance: "simulated",
    result: null,
    scientific_review: "Simulated measurements. Physical validation remains outstanding.",
  };
}

export const recordedAt = "2026-11-12T09:10:47Z";
export function recordedRuns(concentration: Specification, course: Specification): Run[] {
  const stamp = (time: string) => "2026-11-12T" + time + "Z";
  const first: Run = {
    ...queuedRun("fixture-concentration", concentration, stamp("08:59:50")),
    recipe: "verified",
    software: "ready",
    acquisition: "completed",
    analysis: "completed",
    blockers: [],
    preparation: "generation",
    release_id: "uvvis-concentration-v1",
    job_id: "job-101",
    source_revision: "6c0483ae",
    software_wait_s: 6,
    software_started_at: stamp("08:59:53"),
    software_finished_at: stamp("09:00:18"),
    acquisition_started_at: stamp("09:00:01"),
    acquisition_finished_at: stamp("09:00:12"),
    analysis_started_at: stamp("09:00:18"),
    analysis_finished_at: stamp("09:00:20"),
    result: {
      calibration_id: "cal-visible-01",
      unit: "mg/L",
      results: [
        { sample_id: "vial-q17", concentration_mg_l: 4.8, replicate_sd_mg_l: 0.12, review_reason: null },
      ],
    },
  };
  const second: Run = {
    ...queuedRun("fixture-time-course", course, stamp("09:04:50")),
    recipe: "verified",
    software: "ready",
    acquisition: "completed",
    analysis: "completed",
    blockers: [],
    preparation: "reuse",
    release_id: "uvvis-time-course-v2",
    job_id: "job-102",
    source_revision: "d23dc09b",
    software_wait_s: 0,
    software_started_at: stamp("09:04:51"),
    software_finished_at: stamp("09:04:53"),
    acquisition_started_at: stamp("09:05:00"),
    acquisition_finished_at: stamp("09:05:38"),
    analysis_started_at: stamp("09:05:39"),
    analysis_finished_at: stamp("09:05:40"),
    result: {
      calibration_id: "cal-visible-01",
      unit: "mg/L",
      results: [
        {
          sample_id: "vial-q17",
          concentration_mg_l: 4.91,
          replicate_sd_mg_l: 0.06,
          review_reason: null,
          timestamp: stamp("09:05:03"),
          elapsed_s: 3,
        },
        {
          sample_id: "vial-q17",
          concentration_mg_l: null,
          replicate_sd_mg_l: null,
          review_reason: "Outside calibration range",
          timestamp: stamp("09:05:35"),
          elapsed_s: 35,
        },
      ],
    },
  };
  return [
    first,
    second,
    {
      ...queuedRun("fixture-pending", concentration, stamp("09:10:01")),
      recipe: "verified",
      preparation: "revision",
      software: "running",
      acquisition: "completed",
      software_started_at: stamp("09:10:03"),
      acquisition_started_at: stamp("09:10:06"),
      acquisition_finished_at: stamp("09:10:30"),
      job_id: "job-103",
      software_wait_s: 17,
      software_wait_pending: true,
      blockers: ["Waiting for a compatible verified release"],
    },
    {
      ...queuedRun("fixture-interrupted", course, stamp("09:06:50")),
      recipe: "verified",
      software: "failed",
      acquisition: "interrupted",
      analysis: "pending",
      job_id: "job-104",
      preparation: "revision",
      software_started_at: stamp("09:06:52"),
      software_finished_at: stamp("09:07:13"),
      acquisition_started_at: stamp("09:07:00"),
      acquisition_finished_at: stamp("09:07:16"),
      blockers: ["Interrupted acquisition; partial measurements retained", "Software preparation failed"],
    },
  ];
}
