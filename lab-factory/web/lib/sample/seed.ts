// The sample workspace: one lab, two projects, two experiments, three orders,
// conversations, an analysis app, a simulation, skills and connectors.
// createSeed builds a completely fresh object graph on every call.
import { canonicalDigest } from "../digest.ts";
import { SAMPLE_READINGS, toCsv } from "../readings.ts";
import { submissionSummary } from "../status.ts";
import type {
  AnalysisApp, Connector, Document, Experiment, HistoryEvent, Lab, LabSettings, Message, Pin,
  ProcedureStep, Project, Revision, RunPlan, RunStepView, Simulation, Skill, StepView, Submission,
  WorkOrder,
} from "../types.ts";
import { ANALYSIS_CODE, SIMULATION_CODE } from "./code.ts";
import {
  procedureResults, procedureViews, referenceCases, runPlanResults, runPlanViews, sampleB12Experiment,
  sampleLab,
} from "./content.ts";

export type SampleState = {
  lab: Lab; settings: LabSettings; projects: Project[]; experiments: Experiment[];
  revisions: Record<string, Revision[]>; orders: WorkOrder[]; submissions: Submission[];
  views: Record<string, (StepView | RunStepView)[]>; history: Record<string, HistoryEvent[]>;
  messages: Record<string, Message[]>; apps: Record<string, AnalysisApp>;
  simulations: Record<string, Simulation>; skills: Skill[]; connectors: Connector[];
};

function skills(): Skill[] {
  return [
    {
      id: "procedure-style",
      title: "How we write procedures",
      description: "Short instructions with a source for every step.",
      body: [
        "- Write each step as one short instruction.",
        "- Cite at least one lab, project or experiment document in every step.",
        "- Put instrument settings in the step's action, never in its text.",
        "- Put hand-measured quantities in amounts.",
      ].join("\n"),
      enabled: true,
      revision: 1,
    },
    {
      id: "reporting-units",
      title: "Units we report in",
      description: "Concentrations in mg/L, rates per second.",
      body: "- Report concentrations in mg/L.\n- Report rate constants per second and half-lives in seconds.",
      enabled: true,
      revision: 1,
    },
    {
      id: "plot-style",
      title: "Plotting conventions",
      description: "Units on every axis, points for data, lines for fits.",
      body: "- Label every axis with its unit.\n- Show measured data as points and fitted curves as lines.",
      enabled: false,
      revision: 1,
    },
  ];
}

function connectors(): Connector[] {
  return [
    {
      id: "google_drive", name: "Google Drive", provides: "Protocols and papers", connected: false, account: null,
      items: [{ id: "drive-dye-protocol", kind: "sop", title: "Coomassie dye protocol (sample)",
                text: "Dissolve the dye in the buffer, filter it, and store it in the dark." }],
    },
    {
      id: "zotero", name: "Zotero", provides: "Papers", connected: true, account: "Emory Biophysics library",
      items: [{ id: "zotero-dye-reduction", kind: "paper", title: "Reduction of triarylmethane dyes (sample)",
                text: "Triarylmethane dyes lose their colour when the central carbon is reduced." }],
    },
    {
      id: "eln", name: "Lab notebook (Benchling and others)", provides: "Notebook entries and protocols",
      connected: false, account: null,
      items: [{ id: "eln-dye-stock", kind: "note", title: "Notebook entry: dye stock (sample)",
                text: "Dye stock made fresh in the lab buffer and kept covered." }],
    },
    {
      id: "instrument_folder", name: "Instrument data folder", provides: "Readings exported by your instruments",
      connected: true, account: "uvvis-1 exports",
      items: [{ id: "coomassie-run-1.csv", kind: "readings", title: "coomassie-run-1.csv", text: toCsv(SAMPLE_READINGS) }],
    },
    {
      id: "github", name: "GitHub", provides: "Existing analysis code", connected: false, account: null,
      items: [{ id: "gh-fit-utils", kind: "code", title: "fit_utils.py (sample)",
                text: "def half_life(k):\n    return 0.6931471805599453 / k\n" }],
    },
  ];
}

function wo1Steps(): ProcedureStep[] {
  const read = (extra: { parameter: string; value: number; unit: string }[] = []) => ({
    instrument_id: "uvvis-1",
    command: "read_absorbance",
    settings: [{ parameter: "wavelength", value: 595, unit: "nm" }, ...extra],
  });
  return [
    {
      text: "Prepare the dye solution as described in the dye preparation note.",
      citations: ["coomassie-dye-prep"],
      amounts: [{ what: "dye solution", value: 1, unit: "mL" }],
    },
    { text: "Blank the spectrophotometer with solvent only.", citations: ["sop-cuvette"], action: read() },
    {
      text: "Bring the cuvette to temperature.",
      citations: ["sop-cuvette"],
      action: {
        instrument_id: "uvvis-1",
        command: "set_temperature",
        settings: [{ parameter: "temperature", value: 298.15, unit: "K" }],
      },
    },
    { text: "Add the reducing agent and mix.", citations: [] },
    {
      text: "Record absorbance as the blue fades.",
      citations: ["coomassie-dye-prep"],
      action: read([{ parameter: "integration_time", value: 1, unit: "s" }]),
    },
  ];
}

// The backend's procedure example (ARTIFACT_EXAMPLES["procedure"] in artifacts.py).
function b12Steps(): ProcedureStep[] {
  return [
    { text: "Rinse the cuvette twice with buffer.", citations: ["sop-cuvette"] },
    {
      text: "Pipette the sample into the cuvette.",
      citations: ["b12-protocol"],
      amounts: [{ what: "sample", value: 1, unit: "mL" }],
    },
    {
      text: "Place the cuvette in the holder and read the absorbance.",
      citations: ["sop-cuvette"],
      action: {
        instrument_id: "uvvis-1",
        command: "read_absorbance",
        settings: [{ parameter: "wavelength", value: 550, unit: "nm" }],
      },
    },
  ];
}

export async function createSeed(now: Date): Promise<SampleState> {
  const ago = (minutes: number): string => new Date(now.getTime() - minutes * 60_000).toISOString();
  const day3 = 3 * 24 * 60;

  const lab = sampleLab();
  const projects: Project[] = [
    {
      id: "coomassie-reduction",
      lab_id: lab.id,
      title: "Coomassie reduction",
      goals: "Follow the reduction of Coomassie blue's central carbon by the loss of its blue absorbance.",
      documents: [{
        id: "coomassie-dye-prep",
        kind: "note",
        title: "Dye stock preparation",
        source: "Project notes",
        text: "Dissolve the dye in the buffer named in the lab notebook and filter before use.",
      }],
    },
    { id: "b12-quantification", lab_id: lab.id, title: "B12 quantification", goals: "Measure vitamin B12 in reference solutions.", documents: [] },
  ];
  const experiments: Experiment[] = [
    {
      id: "coomassie-run-1",
      lab_id: lab.id,
      project_id: "coomassie-reduction",
      title: "Reducing Coomassie blue",
      goal: "Reduce the central carbon of Coomassie blue and follow it on the spectrophotometer.",
      instrument_ids: ["uvvis-1"],
      documents: [],
    },
    sampleB12Experiment(),
  ];
  const skillList = skills();

  // Revision digests. Experiment digests leave out project_id, as the backend's record has none.
  const revisions: Record<string, Revision[]> = {};
  const addRevision = async (key: string, record: unknown): Promise<string> => {
    const digest = await canonicalDigest(record);
    revisions[key] = [{ number: 1, digest, at: ago(day3), note: "Created" }];
    return digest;
  };
  const labDigest = await addRevision(`lab:${lab.id}`, lab);
  const projectDigests: Record<string, string> = {};
  for (const p of projects) projectDigests[p.id] = await addRevision(`project:${p.id}`, p);
  const experimentDigests: Record<string, string> = {};
  for (const e of experiments) {
    const { project_id: _project, ...record } = e;
    experimentDigests[e.id] = await addRevision(`experiment:${e.id}`, record);
  }
  const skillDigests: Record<string, string> = {};
  for (const s of skillList) {
    const { enabled: _enabled, revision: _revision, ...record } = s;
    skillDigests[s.id] = await addRevision(`skill:${s.id}`, record);
  }

  const pinsFor = (experimentId: string): Pin[] => {
    const e = experiments.find((x) => x.id === experimentId)!;
    return [
      { kind: "lab", id: lab.id, revision: 1, digest: labDigest },
      { kind: "project", id: e.project_id, revision: 1, digest: projectDigests[e.project_id] },
      { kind: "experiment", id: e.id, revision: 1, digest: experimentDigests[e.id] },
      ...skillList.filter((s) => s.enabled).map((s): Pin => ({ kind: "skill", id: s.id, revision: 1, digest: skillDigests[s.id] })),
    ];
  };
  const docsFor = (experimentId: string): Document[] => {
    const e = experiments.find((x) => x.id === experimentId)!;
    const p = projects.find((x) => x.id === e.project_id)!;
    return [...lab.documents, ...p.documents, ...e.documents];
  };

  const orders: WorkOrder[] = [
    {
      id: "WO-1", experiment_id: "coomassie-run-1", kind: "procedure",
      objective: "Write a procedure for reducing Coomassie blue.", status: "in_progress",
      released_submission: null, pins: pinsFor("coomassie-run-1"),
    },
    {
      id: "WO-B12", experiment_id: "b12-vial-a", kind: "procedure",
      objective: "Write a procedure for measuring vitamin B12 absorbance.", status: "in_review",
      released_submission: null, pins: pinsFor("b12-vial-a"),
    },
    {
      id: "WO-B12-RP", experiment_id: "b12-vial-a", kind: "run_plan",
      objective: "Write a run plan for the vitamin B12 absorbance reads.", status: "in_progress",
      released_submission: null, pins: pinsFor("b12-vial-a"),
    },
  ];

  // Submissions, results and views.
  const instruments = lab.instruments;
  const submit = async (orderId: string, artifact: unknown, results: Submission["results"], minutes: number): Promise<Submission> => ({
    work_order_id: orderId,
    number: 1,
    artifact,
    artifact_digest: await canonicalDigest(artifact),
    results,
    passed: results.length > 0 && results.every((r) => r.passed),
    submitted_at: ago(minutes),
  });

  const wo1Artifact = { steps: wo1Steps() };
  const wo1Results = procedureResults(wo1Artifact.steps, docsFor("coomassie-run-1"), instruments, false);
  const b12Artifact = { steps: b12Steps() };
  const b12Results = procedureResults(b12Artifact.steps, docsFor("b12-vial-a"), instruments, true);
  const rpArtifact: RunPlan = {
    instrument_id: "uvvis-1",
    steps: [{ command: "read_absorbance", settings: [{ parameter: "wavelength", value: 750, unit: "nm" }] }],
  };
  const rpResults = runPlanResults(rpArtifact, instruments);

  const wo1Submission = await submit("WO-1", wo1Artifact, wo1Results, 80);
  const b12Submission = await submit("WO-B12", b12Artifact, b12Results, 180);
  const rpSubmission = await submit("WO-B12-RP", rpArtifact, rpResults, 175);
  const submissions = [wo1Submission, b12Submission, rpSubmission];
  const views: SampleState["views"] = {
    "WO-1#1": procedureViews(wo1Artifact.steps, wo1Results, docsFor("coomassie-run-1"), instruments),
    "WO-B12#1": procedureViews(b12Artifact.steps, b12Results, docsFor("b12-vial-a"), instruments),
    "WO-B12-RP#1": runPlanViews(rpArtifact, rpResults, instruments),
  };

  const failedCount = wo1Results.filter((r) => !r.passed).length;
  const history = (claimer: string, created: number, claimed: number, submitted: number, note: string): HistoryEvent[] => [
    { event: "created", actor: "factory", submission: null, note: "", at: ago(created) },
    { event: "claimed", actor: claimer, submission: null, note: "", at: ago(claimed) },
    { event: "submitted", actor: claimer, submission: 1, note, at: ago(submitted) },
  ];

  const coomassie = experiments[0];
  const app: AnalysisApp = {
    summary: "Turns absorbance over time into a rate constant and half-life.",
    code: ANALYSIS_CODE,
    entry: "analyze",
    reference_cases: referenceCases(),
  };
  const simulation: Simulation = {
    title: "Fading curves for three amounts of reducing agent",
    summary: "Predicted absorbance at the blue peak if the rate scales with the amount of reducing agent.",
    code: SIMULATION_CODE,
    entry: "simulate",
    x_label: "Time (s)",
    y_label: "Absorbance (AU)",
  };

  const messages: SampleState["messages"] = {
    "coomassie-run-1": [
      { id: "coomassie-run-1-m1", from: "person", text: coomassie.goal, at: ago(90) },
      {
        id: "coomassie-run-1-m2", from: "factory", at: ago(89),
        text: "I can build a procedure, an analysis app that fits the fading curve, and a simulation of the reaction.",
        proposal: { outputs: ["procedure", "analysis_app", "simulation"], accepted: ["procedure", "analysis_app", "simulation"] },
      },
      {
        id: "coomassie-run-1-m3", from: "factory", at: ago(79),
        text: "Built. Step 4 has no source for the reducing agent. Attach the protocol or paper you’re working from and I’ll rewrite the procedure.",
        activity: [
          { id: "a1", label: "Read lab context (revision 1)", outcome: "done" },
          { id: "a2", label: "Read project context (revision 1)", outcome: "done" },
          { id: "a3", label: "Wrote procedure", outcome: "done" },
          { id: "a4", label: `Ran ${wo1Results.length} checks: ${failedCount} failed`, outcome: "failed", detail: "step 4: citations: no citation" },
          { id: "a5", label: "Wrote analysis app", outcome: "done" },
          { id: "a6", label: `Prepared ${app.reference_cases.length} reference cases`, outcome: "info" },
          { id: "a7", label: "Wrote simulation", outcome: "done" },
        ],
        output_refs: [
          { kind: "procedure", work_order_id: "WO-1", summary: submissionSummary(wo1Submission) },
          { kind: "analysis_app", summary: app.summary },
          { kind: "simulation", summary: simulation.title },
        ],
      },
    ],
    "b12-vial-a": [
      { id: "b12-vial-a-m1", from: "person", text: experiments[1].goal, at: ago(200) },
      {
        id: "b12-vial-a-m2", from: "factory", at: ago(170),
        text: "Built a procedure, which is waiting for sign-off, and a run plan, which fails one check.",
        output_refs: [
          { kind: "procedure", work_order_id: "WO-B12", summary: submissionSummary(b12Submission) },
          { kind: "run_plan", work_order_id: "WO-B12-RP", summary: submissionSummary(rpSubmission) },
        ],
      },
    ],
  };

  return {
    lab,
    settings: { sign_off: { mode: "anyone" } },
    projects,
    experiments,
    revisions,
    orders,
    submissions,
    views,
    history: {
      "WO-1": history("factory", 88, 87, 80, "failed"),
      "WO-B12": history("codex on lab-pc", 199, 190, 180, "passed"),
      "WO-B12-RP": history("codex on lab-pc", 199, 185, 175, "failed"),
    },
    messages,
    apps: { "coomassie-run-1": app },
    simulations: { "coomassie-run-1": simulation },
    skills: skillList,
    connectors: connectors(),
  };
}
