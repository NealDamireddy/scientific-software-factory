import { playbooks } from "./playbooks.ts";
import type { Finding, ResearchSkill, ReviewInput } from "./types";

type BriefingField =
  "objective" | "project" | "methodName" | "methodRevision" | "wavelengthNm";

const methodFields: [BriefingField, string][] = [
  ["methodName", "method name"],
  ["methodRevision", "method revision"],
];
const setupFields: [BriefingField, string][] = [
  ["objective", "objective"],
  ["project", "project"],
  ...methodFields,
  ["wavelengthNm", "wavelength"],
];

function reviewBriefing(
  input: ReviewInput,
  fields: [BriefingField, string][],
  complete: string,
): Finding | null {
  if (input.kind !== "b12" && input.kind !== "time-course") return null;

  const references: string[] = [];
  const missing: string[] = [];
  const run =
    Number.isInteger(input.runNumber) && input.runNumber > 0
      ? `Run ${input.runNumber} briefing`
      : "Run briefing";
  let invalidWavelength = false;
  for (const [field, label] of fields) {
    const value = input[field];
    let recorded: string | undefined;
    if (field === "wavelengthNm") {
      if (typeof value === "number" && Number.isFinite(value)) {
        recorded = `${value} nm`;
        invalidWavelength = value <= 0;
      }
    } else if (typeof value === "string" && value.trim()) {
      recorded = value.trim();
    }
    if (recorded === undefined) {
      missing.push(label);
    } else {
      references.push(`${run} · ${label} · ${recorded}`);
    }
  }
  const gap = missing.length
    ? `Usable briefing evidence is missing for ${missing.join(", ")}.`
    : "";
  if (invalidWavelength) {
    return {
      verdict: "finding",
      finding: [
        `The recorded wavelength of ${input.wavelengthNm} nm must be positive.`,
        gap,
      ]
        .filter(Boolean)
        .join(" "),
      references,
    };
  }
  return gap
    ? { verdict: "unassessed", finding: gap, references }
    : { verdict: "clear", finding: complete, references };
}

export const planningSkills: ResearchSkill[] = [
  {
    id: "method-reference",
    name: "Method reference",
    family: "Lab knowledge",
    stage: "start",
    description: "Identify the method and revision cited by a run.",
    input: "Method name and revision from the run briefing.",
    output:
      "Method identification status with the available briefing references.",
    whenToUse: "When a record identifies the procedure used.",
    instructions: playbooks["method-reference"],
    evaluate: (input) =>
      reviewBriefing(
        input,
        methodFields,
        "The briefing identifies the method and its revision.",
      ),
  },
  {
    id: "protocol-readiness",
    name: "Run setup completeness",
    family: "Experiment planning",
    stage: "start",
    description:
      "Check whether the recorded setup includes the fields needed for the stated measurement.",
    input:
      "Run objective, project, method revision and the measurement settings required by that method.",
    output:
      "Briefing readiness with field references and any missing or invalid setup.",
    whenToUse: "Before a run or when auditing its original briefing.",
    instructions: playbooks["protocol-readiness"],
    evaluate: (input) =>
      reviewBriefing(
        input,
        setupFields,
        "The briefing records the objective, project, versioned method, and measurement wavelength.",
      ),
  },
];
