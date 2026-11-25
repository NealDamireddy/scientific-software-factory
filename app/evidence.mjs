// Reads an EPR factory report.json and says what its checks show.
// The workbench uses these helpers so that every label, pipeline step and
// headline comes from report.checks, never from a per-project story.

export const checkNames = {
  "metadata": "Acquisition metadata",
  "units": "Input units",
  "schema": "Dataset schema",
  "parameters": "Processing parameters",
  "fixture identity": "Reference fingerprint",
  "execution": "Python execution",
  "reference": "Numerical references",
  "provenance": "Artifact provenance",
  "physical instrument": "Physical instrument",
  "read-export": "Read normalized exports",
  "measure-linewidth": "Measure derivative linewidth",
  "fit-curie": "Fit temperature series",
  "pulse-acquisition": "Pulse acquisition",
  "vendor-binary": "Vendor binary import",
};
export const checkName = name => checkNames[name] || name;

const FAILED = new Set(["fail", "failed", "unknown"]);
// Checks that describe the whole evidence package rather than a pipeline stage.
const OUTSIDE_PIPELINE = new Set(["provenance", "physical instrument"]);
const STAGE_OF_CHECK = {execution: "Execute", reference: "Verify"};

export const stageOf = check =>
  OUTSIDE_PIPELINE.has(check.name) ? null : STAGE_OF_CHECK[check.name] || "Preflight";

/** The first check that failed, or undefined when nothing failed. */
export function blockingCheck(report) {
  return report.checks.find(c => FAILED.has(c.status));
}

/** The "physical instrument" check when it was not exercised. */
export function untestedInstrument(report) {
  return report.checks.find(c => c.name === "physical instrument" && c.status !== "pass");
}

/** Short label for a run in the history list. */
export function runLabel(report) {
  const blocking = blockingCheck(report);
  if (blocking) return checkName(blocking.name) + " failed";
  if (report.status === "verified") {
    const reference = report.checks.find(c => c.name === "reference");
    return reference?.detail?.replace(/\.$/, "") || "Reference verification passed";
  }
  const pending = report.checks.find(c => c.status === "untested" && !OUTSIDE_PIPELINE.has(c.name));
  return pending ? checkName(pending.name) + " untested" : "Status: " + report.status;
}

const STAGES = [
  ["Context", "Lab and project"],
  ["Preflight", "Profile constraints"],
  ["Generate", "Codex CLI"],
  ["Execute", "Isolated Python"],
  ["Verify", "Reference suite"],
];

function stageState(checks) {
  if (!checks.length) return "pass";
  if (checks.some(c => FAILED.has(c.status))) return "fail";
  if (checks.every(c => c.status === "pass")) return "pass";
  return "untested";
}

/**
 * Pipeline steps, each with a state of pass, fail, untested or skipped.
 * A stage after one that did not pass is "skipped" (not reached).
 */
export function pipelineStages(report) {
  let reached = true;
  return STAGES.map(([name, description]) => {
    let state;
    if (!reached) state = "skipped";
    else if (name === "Context") state = "pass";
    else if (name === "Generate") state = report.source_revision ? "pass" : "fail";
    else state = stageState(report.checks.filter(c => stageOf(c) === name));
    if (state !== "pass") reached = false;
    const failed = state === "fail" && report.checks.find(c => stageOf(c) === name && FAILED.has(c.status));
    return {name, description, state, check: failed || undefined};
  });
}

/** Headline and detail for the Verification tab. */
export function verificationHeadline(report) {
  if (report.status === "verified" && !blockingCheck(report))
    return {title: "Reference verification passed", detail: null};
  const stopped = pipelineStages(report).find(s => s.state !== "pass");
  const verb = report.status === "blocked" ? "Work order blocked" : "Run " + report.status;
  const blocking = blockingCheck(report);
  return {
    title: stopped ? verb + " at " + stopped.name.toLowerCase() : verb,
    detail: blocking ? checkName(blocking.name) + ": " + blocking.detail : null,
  };
}

/**
 * Which run to show for a project: the selected one, else the newest
 * verified run, else the newest run of any status. Undefined when the
 * project has no runs. `runs` must be sorted newest first.
 */
export function currentRun(runs, project, selected) {
  const projectRuns = runs.filter(r => r.report.project === project);
  return projectRuns.find(r => r.report.id === selected)
    || projectRuns.find(r => r.report.status === "verified")
    || projectRuns[0];
}
