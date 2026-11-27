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
    description: "Checks whether the run identifies a method and its revision.",
    input: "Method name and revision from the run briefing.",
    output:
      "Method identification status with the available briefing references.",
    whenToUse:
      "At the start of an original or repeat simulated B12 or time-course measurement.",
    instructions:
      "Read the method name and revision from this run’s briefing. Cite both as recorded. If either is missing or blank, name the missing field and leave identification unassessed.",
    evaluate: (input) =>
      reviewBriefing(
        input,
        methodFields,
        "The briefing identifies the method and its revision.",
      ),
  },
  {
    id: "protocol-readiness",
    name: "Protocol readiness",
    family: "Experiment planning",
    stage: "start",
    description:
      "Checks whether the planned measurement has an objective, a project, a versioned method, and a wavelength.",
    input:
      "Run objective, project, method name, method revision, and wavelength in nm.",
    output:
      "Briefing readiness with field references and any missing or invalid setup.",
    whenToUse:
      "At the start of an original or repeat simulated B12 or time-course measurement.",
    instructions:
      "Inspect the current briefing and cite each usable field. Flag a recorded wavelength of zero or less. Identify missing text and missing or nonfinite wavelengths as evidence gaps. Mark the setup clear only when every required field is present and the wavelength is positive.",
    evaluate: (input) =>
      reviewBriefing(
        input,
        setupFields,
        "The briefing records the objective, project, versioned method, and measurement wavelength.",
      ),
  },
];
