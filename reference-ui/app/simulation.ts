import type { WorkerDelivery } from "./worker-delivery";
import type { AgentContext } from "./extension-model";
import { researchSkills } from "./review-skills/catalog.ts";
import type { ReviewInput, Stage, Verdict } from "./review-skills/types";

export type Status =
  | "Draft"
  | "Running"
  | "Awaiting approval"
  | "Changes requested"
  | "Cancelled"
  | "Verified";
export type Kind = "b12" | "time-course";
export type Reading = { x: number; y: number };
export type AgentBriefing = {
  objective: string;
  project: string;
  method: { name: string; revision: string; wavelengthNm: number };
  mode: "original" | "repeat";
  instrument?: string;
};
export type RunContext = AgentContext & { briefing: AgentBriefing };
export type AgentCheck = {
  skillId: string;
  finding: string;
  verdict?: Verdict;
  stage?: Stage;
  references?: string[];
};
export type Run = {
  number: number;
  mode: "original" | "repeat";
  step: number;
  agentContext?: RunContext;
  agentChecks?: AgentCheck[];
  workerDelivery?: WorkerDelivery;
  approval?: { originalRunNumber: number; dilutionFactor: number };
  outcome: "running" | "flagged" | "verified" | "cancelled";
};
export type Event = { title: string; detail: string };
export type Experiment = {
  id: string;
  title: string;
  project: string;
  kind: Kind;
  status: Status;
  runs: Run[];
  events: Event[];
};
export const simulationInstrument = "UV–Vis spectrometer";
export const repeatDilutionFactor = 2;
export const sampleOriginal = 1.25;
export const sampleRepeat = 0.65;
export const resultConcentration = Number(
  (((sampleRepeat - 0.05) / 0.08) * repeatDilutionFactor).toFixed(1),
);
export const standards: Reading[] = [0, 2, 4, 6, 8, 10].map((x) => ({
  x,
  y: Number((0.05 + 0.08 * x).toFixed(3)),
}));
export const timeCourse: Reading[] = [
  0.82, 0.701, 0.611, 0.544, 0.489, 0.445, 0.413, 0.388, 0.367,
].map((y, i) => ({ x: i * 15, y }));
function classify(title: string, project: string): Kind {
  return /coomassie|time[ -]?course|reduction|kinetic/i.test(
    title + " " + project,
  )
    ? "time-course"
    : "b12";
}
export function createDraft(title: string, project: string): Experiment {
  return {
    id: crypto.randomUUID(),
    title,
    project,
    kind: classify(title, project),
    status: "Draft",
    runs: [],
    events: [
      { title: "Draft created", detail: "Researcher · illustrative workspace" },
    ],
  };
}
export const methodName = (kind: Kind) =>
  kind === "b12" ? "Vitamin B12 calibration" : "Coomassie reduction kinetics";
export const wavelength = (kind: Kind) => (kind === "b12" ? 361 : 595);
export function prepareRunContext(
  e: Experiment,
  mode: Run["mode"],
  configuration: AgentContext,
): RunContext {
  return {
    ...structuredClone(configuration),
    briefing: {
      objective: e.title,
      instrument: simulationInstrument,
      project: e.project,
      method: {
        name: methodName(e.kind),
        revision: "1.0",
        wavelengthNm: wavelength(e.kind),
      },
      mode,
    },
  };
}

function simulatedAgentChecks(e: Experiment, run: Run): AgentCheck[] {
  const context = run.agentContext;
  if (!context) return [];
  const checks: AgentCheck[] = [];
  const points = readings(e, run);
  for (const skill of context.skills) {
    if (skill.id === "calibration" && e.kind === "b12") {
      const sample = run.mode === "original" ? sampleOriginal : sampleRepeat;
      const low = Math.min(...points.map((p) => p.y)),
        high = Math.max(...points.map((p) => p.y));
      const within = sample >= low && sample <= high;
      const finding = within
        ? "The diluted sample is within range. The recorded dilution factor is 2×."
        : "The original sample is outside range. Concentration withheld.";
      checks.push({
        skillId: skill.id,
        verdict: within ? "clear" : "finding",
        stage: "result",
        references: [
          `Run ${run.number} · calibration standards`,
          `Run ${run.number} · sample absorbance`,
        ],
        finding: `Run ${run.number}: ${sample.toFixed(3)} AU against ${low.toFixed(3)}–${high.toFixed(3)} AU. ${finding}`,
      });
    }
    if (skill.id === "evidence") {
      const first = points[0],
        last = points.at(-1)!;
      checks.push({
        skillId: skill.id,
        verdict: "clear",
        stage: "result",
        references: [
          `Run ${run.number} · source readings`,
          `Run ${run.number} · method revision`,
        ],
        finding: `Run ${run.number} · ${context.briefing.method.name} v${context.briefing.method.revision}. ${points.length} ${e.kind === "b12" ? "calibration standards" : "time points"} recorded at ${context.briefing.method.wavelengthNm} nm. First reading ${first.y.toFixed(3)} AU, last reading ${last.y.toFixed(3)} AU.`,
      });
    }
  }
  return checks;
}

export function reviewInput(e: Experiment, run: Run): ReviewInput {
  const brief = run.agentContext?.briefing;
  const completed = run.outcome === "flagged" || run.outcome === "verified";
  const parent =
    run.approval &&
    e.runs.find(
      (r) =>
        r.number === run.approval!.originalRunNumber && r.mode === "original",
    );
  return {
    runNumber: run.number,
    kind: e.kind,
    mode: run.mode,
    objective: brief?.objective,
    project: brief?.project,
    methodName: brief?.method.name,
    methodRevision: brief?.method.revision,
    wavelengthNm: brief?.method.wavelengthNm,
    instrument: brief?.instrument,
    readings: readings(e, run),
    ...(completed && e.kind === "b12"
      ? {
          sampleAU: run.mode === "original" ? sampleOriginal : sampleRepeat,
          dilutionFactor: run.mode === "original" ? 1 : repeatDilutionFactor,
          reportedConcentration:
            run.outcome === "flagged" ? null : resultConcentration,
        }
      : {}),
    ...(run.approval
      ? { approvedDilutionFactor: run.approval.dilutionFactor }
      : {}),
    ...(parent
      ? {
          original: {
            runNumber: parent.number,
            outcome: parent.outcome,
            ...(e.kind === "b12" && parent.outcome === "flagged"
              ? { sampleAU: sampleOriginal }
              : {}),
          },
        }
      : {}),
  };
}

function evaluateStage(e: Experiment, run: Run, stage: Stage): AgentCheck[] {
  const enabled = run.agentContext?.skills;
  if (!enabled?.length) return [];
  const input = reviewInput(e, run);
  const checks: AgentCheck[] = [];
  for (const skill of researchSkills) {
    if (
      skill.stage !== stage ||
      !enabled.some(
        (item) =>
          item.id === skill.id && "source" in item && item.source === "builtin",
      )
    )
      continue;
    const finding = skill.evaluate(input);
    if (finding) checks.push({ skillId: skill.id, stage, ...finding });
  }
  return checks;
}

function methodComparison(e: Experiment, run: Run): AgentCheck[] {
  if (
    run.mode !== "repeat" ||
    !run.agentContext?.skills.some(
      (skill) =>
        skill.id === "method" &&
        "source" in skill &&
        skill.source === "builtin",
    )
  )
    return [];
  const parent = e.runs.find(
    (prior) => prior.number === run.approval?.originalRunNumber,
  );
  const before = parent?.agentContext?.briefing.method;
  const after = run.agentContext.briefing.method;
  const refs: string[] = [];
  if (parent) refs.push(`Run ${parent.number} · original record`);
  if (before)
    refs.push(
      `Run ${parent?.number} · ${before.name} v${before.revision} · ${before.wavelengthNm} nm`,
    );
  refs.push(
    `Run ${run.number} · ${after.name} v${after.revision} · ${after.wavelengthNm} nm`,
  );
  const record = (verdict: Verdict, finding: string): AgentCheck[] => [
    { skillId: "method", stage: "repeat", verdict, finding, references: refs },
  ];
  if (
    !before?.revision ||
    !Number.isFinite(before.wavelengthNm) ||
    !after.revision ||
    !Number.isFinite(after.wavelengthNm)
  ) {
    return record(
      "unassessed",
      "A complete method revision and wavelength are required for both linked runs.",
    );
  }
  const changed =
    before.name !== after.name ||
    before.revision !== after.revision ||
    before.wavelengthNm !== after.wavelengthNm;
  return changed
    ? record(
        "finding",
        "The recorded method settings differ between the original and repeat. Review the linked revisions when comparing their readings.",
      )
    : record(
        "clear",
        `Both linked runs record ${after.name} v${after.revision} at ${after.wavelengthNm} nm.`,
      );
}

export function pendingReview(
  skill: AgentContext["skills"][number],
  run: Run,
): [string, string] {
  const builtin = "source" in skill && skill.source === "builtin";
  if (!builtin) return ["Loaded only", "Instructions included as reference."];
  const stage =
    researchSkills.find((s) => s.id === skill.id)?.stage ??
    (skill.id === "method"
      ? "repeat"
      : ["calibration", "evidence"].includes(skill.id)
        ? "result"
        : undefined);
  if (!stage) return ["Loaded only", "Instructions included as reference."];
  if (stage === "repeat" && run.mode !== "repeat")
    return ["Not triggered", "Applies only to a completed repeat."];
  if (run.outcome === "running" && stage !== "start")
    return ["Pending", "Scheduled for run completion."];
  if (run.outcome === "cancelled" && stage !== "start")
    return ["Not triggered", "The run was cancelled before this review stage."];
  return [
    "Not triggered",
    "This review does not apply to the recorded inputs.",
  ];
}

export function startRun(
  e: Experiment,
  mode: Run["mode"] = "original",
  configuration?: AgentContext,
  deliveryId?: string,
): Experiment {
  const previous = e.runs.at(-1);
  if (
    e.status === "Running" ||
    (mode === "repeat" &&
      (e.status !== "Awaiting approval" ||
        previous?.outcome !== "flagged" ||
        previous.mode !== "original"))
  )
    return e;
  const number = e.runs.length + 1;
  const events = [...e.events];
  if (mode === "repeat")
    events.push({
      title: "Repeat approved",
      detail: "Researcher · 2× dilution authorized",
    });
  events.push({
    title: "Run " + number + " started",
    detail:
      "UV–Vis spectrometer · " +
      (mode === "repeat" ? "2× dilution" : "original sample"),
  });
  const run: Run = { number, mode, step: 0, outcome: "running" };
  if (
    mode === "repeat" &&
    previous?.outcome === "flagged" &&
    previous.mode === "original"
  ) {
    run.approval = {
      originalRunNumber: previous.number,
      dilutionFactor: repeatDilutionFactor,
    };
  }
  if (configuration) {
    run.agentContext = prepareRunContext(e, mode, configuration);
    run.workerDelivery = { id: deliveryId ?? crypto.randomUUID(), status: "pending" };
    run.agentChecks = evaluateStage(e, run, "start");
  }
  return {
    ...e,
    status: "Running",
    runs: [...e.runs, run],
    events,
  };
}
export function advance(e: Experiment): Experiment {
  if (e.status !== "Running") return e;
  const run = e.runs.at(-1)!;
  const step = Math.min(4, run.step + 1);
  const flagged = e.kind === "b12" && run.mode === "original";
  const outcome = step < 4 ? "running" : flagged ? "flagged" : "verified";
  const nextRun: Run = { ...run, step, outcome };
  if (step === 4 && nextRun.agentContext)
    nextRun.agentChecks = [
      ...(run.agentChecks ?? []),
      ...simulatedAgentChecks(e, nextRun),
      ...evaluateStage(e, nextRun, "result"),
      ...methodComparison(e, nextRun),
      ...(nextRun.mode === "repeat" ? evaluateStage(e, nextRun, "repeat") : []),
    ];
  return {
    ...e,
    runs: [...e.runs.slice(0, -1), nextRun],
    status: step < 4 ? "Running" : flagged ? "Awaiting approval" : "Verified",
    events:
      step < 4
        ? e.events
        : [
            ...e.events,
            {
              title: "Run " + run.number + (flagged ? " flagged" : " verified"),
              detail: flagged
                ? "Original absorbance exceeded calibration range"
                : "Simulated checks passed",
            },
          ],
  };
}
export function cancel(e: Experiment): Experiment {
  if (e.status !== "Running") return e;
  const run = e.runs.at(-1)!;
  return {
    ...e,
    status: "Cancelled",
    runs: [...e.runs.slice(0, -1), { ...run, outcome: "cancelled" }],
    events: [
      ...e.events,
      {
        title: "Run " + run.number + " cancelled",
        detail: "Partial readings retained",
      },
    ],
  };
}
export function requestChanges(e: Experiment, note: string): Experiment {
  if (e.status !== "Awaiting approval" || !note.trim()) return e;
  return {
    ...e,
    status: "Changes requested",
    events: [...e.events, { title: "Changes requested", detail: note.trim() }],
  };
}
export function resubmit(e: Experiment, note: string): Experiment {
  if (e.status !== "Changes requested" || !note.trim()) return e;
  return {
    ...e,
    status: "Awaiting approval",
    events: [
      ...e.events,
      { title: "Revision submitted for review", detail: note.trim() },
    ],
  };
}
export function readings(e: Experiment, run: Run): Reading[] {
  const data = e.kind === "time-course" ? timeCourse : standards;
  return data.slice(0, Math.ceil((data.length * run.step) / 4));
}
function verified(
  id: string,
  title: string,
  project: string,
  kind: Kind,
): Experiment {
  let e: Experiment = {
    id,
    title,
    project,
    kind,
    status: "Draft",
    runs: [],
    events: [
      { title: "Draft created", detail: "Researcher · illustrative workspace" },
    ],
  };
  e = startRun(e);
  for (let i = 0; i < 4; i++) e = advance(e);
  if (kind === "b12") {
    e = startRun(e, "repeat");
    for (let i = 0; i < 4; i++) e = advance(e);
  }
  return e;
}
export const initialExperiments: Experiment[] = [
  verified(
    "absorbance-time-course",
    "Absorbance time course",
    "Coomassie reduction",
    "time-course",
  ),
  verified(
    "vitamin-b12-concentration",
    "Vitamin B12 concentration",
    "B12 quantification",
    "b12",
  ),
];

export function advanceWorkspace(experiments: Experiment[]): Experiment[] {
  return experiments.map((e) => (e.status === "Running" ? advance(e) : e));
}
export function editObjective(e: Experiment, title: string): Experiment {
  const objective = title.trim();
  if (e.status !== "Draft" || !objective || objective === e.title) return e;
  return {
    ...e,
    title: objective,
    kind: classify(objective, e.project),
    events: [
      ...e.events,
      { title: "Draft objective updated", detail: objective },
    ],
  };
}
