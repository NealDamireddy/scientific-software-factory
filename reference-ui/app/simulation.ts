import type { AgentContext } from "./extension-model";

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
};
export type RunContext = AgentContext & { briefing: AgentBriefing };
export type AgentCheck = { skillId: string; finding: string };
export type Run = {
  number: number;
  mode: "original" | "repeat";
  step: number;
  agentContext?: RunContext;
  agentChecks?: AgentCheck[];
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
export const sampleOriginal = 1.25;
export const sampleRepeat = 0.65;
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
        finding: `Run ${run.number}: ${sample.toFixed(3)} AU against ${low.toFixed(3)}–${high.toFixed(3)} AU. ${finding}`,
      });
    }
    if (skill.id === "evidence") {
      const first = points[0],
        last = points.at(-1)!;
      checks.push({
        skillId: skill.id,
        finding: `Run ${run.number} · ${context.briefing.method.name} v${context.briefing.method.revision}. ${points.length} ${e.kind === "b12" ? "calibration standards" : "time points"} recorded at ${context.briefing.method.wavelengthNm} nm. First reading ${first.y.toFixed(3)} AU, last reading ${last.y.toFixed(3)} AU.`,
      });
    }
  }
  return checks;
}

export function startRun(
  e: Experiment,
  mode: Run["mode"] = "original",
  configuration?: AgentContext,
): Experiment {
  if (
    e.status === "Running" ||
    (mode === "repeat" && e.status !== "Awaiting approval")
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
  return {
    ...e,
    status: "Running",
    runs: [
      ...e.runs,
      {
        number,
        mode,
        step: 0,
        outcome: "running",
        ...(configuration
          ? {
              agentContext: prepareRunContext(e, mode, configuration),
              agentChecks: [],
            }
          : {}),
      },
    ],
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
    nextRun.agentChecks = simulatedAgentChecks(e, nextRun);
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
