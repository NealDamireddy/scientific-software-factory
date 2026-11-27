import { playbooks } from "./playbooks.ts";
import type { Finding, ResearchSkill, ReviewInput } from "./types";

const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function calibratedRange(readings: ReviewInput["readings"]) {
  if (
    !Array.isArray(readings) ||
    readings.length < 2 ||
    !readings.every((point) => finite(point?.x) && finite(point?.y)) ||
    new Set(readings.map((point) => point.x)).size < 2
  )
    return;

  const absorbances = readings.map((point) => point.y);
  const low = Math.min(...absorbances);
  const high = Math.max(...absorbances);
  if (low < high) return { low, high };
}

function assessSample(
  input: ReviewInput,
  run: string,
  references: string[],
  missing: string[],
) {
  const range = calibratedRange(input.readings);
  if (range) {
    references.push(
      `${run} · ${input.readings.length} standards · ${range.low.toFixed(3)}–${range.high.toFixed(3)} AU`,
    );
  } else {
    missing.push(
      "A calibrated range requires finite standards spanning distinct concentrations and absorbances.",
    );
  }
  if (finite(input.sampleAU)) {
    references.push(`${run} · sample ${input.sampleAU.toFixed(3)} AU`);
  } else {
    missing.push("The sample absorbance is missing or nonfinite.");
    return;
  }
  if (!range) return;
  if (input.sampleAU < range.low) return "below";
  if (input.sampleAU > range.high) return "above";
  return "within";
}

function methodAdherence(input: ReviewInput): Finding | null {
  if (input.kind !== "b12") return null;
  if (!Number.isInteger(input.runNumber) || input.runNumber < 1) {
    return {
      verdict: "unassessed",
      finding: "A valid run number is needed to trace the result.",
      references: [],
    };
  }
  const run = `Run ${input.runNumber}`;
  const references = [`${run} · ${input.mode} result`];
  const missing: string[] = [];
  const position = assessSample(input, run, references, missing);
  const concentration = input.reportedConcentration;
  if (concentration === null || finite(concentration)) {
    references.push(
      `Run ${input.runNumber} · reported concentration ${concentration === null ? "withheld" : concentration + " µM"}`,
    );
  } else {
    missing.push(
      "The concentration field needs a finite value or an explicit withholding decision.",
    );
  }
  if (missing.length)
    return { verdict: "unassessed", finding: missing.join(" "), references };

  if (position === "within") {
    return concentration === null
      ? {
          verdict: "unassessed",
          finding:
            "The sample is within range. Concentration was withheld, so there is no numeric result to review.",
          references,
        }
      : {
          verdict: "clear",
          finding:
            "The sample is within the measured calibration range, so the method permits a numeric concentration.",
          references,
        };
  }
  const observation = `The sample is ${position} the measured calibration range.`;
  return concentration === null
    ? {
        verdict: "clear",
        finding: `${observation} Concentration was withheld as required.`,
        references,
      }
    : {
        verdict: "finding",
        finding: `${observation} The reported ${concentration} µM should have been withheld.`,
        references,
      };
}

function repeatComparison(input: ReviewInput): Finding | null {
  if (input.kind !== "b12" || input.mode !== "repeat") return null;
  const validRun = Number.isInteger(input.runNumber) && input.runNumber > 0;
  const repeatLabel = validRun ? `Run ${input.runNumber}` : "Repeat record";
  const references = [`${repeatLabel} · repeat result`];
  const missing: string[] = [];
  if (!validRun) missing.push("The repeat run number is missing or invalid.");
  const issues: string[] = [];
  const original = input.original;
  if (!original) {
    missing.push("The original run record is missing.");
  } else {
    const validNumber =
      Number.isInteger(original.runNumber) && original.runNumber > 0;
    const label = validNumber
      ? `Original run ${original.runNumber}`
      : "Original record";
    if (!validNumber)
      missing.push("The original run number is missing or invalid.");
    else if (validRun && original.runNumber >= input.runNumber)
      issues.push("The linked original must precede the repeat.");
    if (original.outcome?.trim()) {
      references.push(`${label} · outcome ${original.outcome}`);
      if (original.outcome !== "flagged") {
        issues.push(
          `${label} has outcome "${original.outcome}". This B12 repeat requires a flagged original.`,
        );
      }
    } else {
      missing.push("The original outcome is missing.");
    }
    if (finite(original.sampleAU))
      references.push(`${label} · sample ${original.sampleAU.toFixed(3)} AU`);
    else missing.push("The original absorbance is missing or nonfinite.");
  }

  const approved = input.approvedDilutionFactor;
  const actual = input.dilutionFactor;
  for (const [label, factor] of [
    ["approved", approved],
    ["actual", actual],
  ] as const) {
    if (finite(factor)) {
      references.push(`${repeatLabel} · ${label} dilution ${factor}×`);
      if (factor <= 0)
        issues.push(`The ${label} dilution factor must be positive.`);
    } else {
      missing.push(`The ${label} dilution factor is missing or nonfinite.`);
    }
  }
  if (finite(actual) && finite(approved) && actual !== approved) {
    issues.push(
      `Actual dilution ${actual}× differs from the approved ${approved}×.`,
    );
  }
  const position = assessSample(input, repeatLabel, references, missing);
  if (position && position !== "within")
    issues.push(`The repeat is ${position} the measured calibration range.`);
  if (issues.length || missing.length) {
    return {
      verdict: issues.length ? "finding" : "unassessed",
      finding: [...issues, ...missing].join(" "),
      references,
    };
  }
  return {
    verdict: "clear",
    finding: `Original run ${original?.runNumber} measured ${original?.sampleAU} AU. Repeat run ${input.runNumber} measured ${input.sampleAU} AU within range at the approved ${approved}× dilution.`,
    references,
  };
}

export const reviewSkills: ResearchSkill[] = [
  {
    id: "method-adherence",
    name: "Method adherence",
    family: "Scientific review",
    stage: "result",
    description:
      "Compare a reported decision with a specific clause of the method used.",
    input:
      "Versioned method clause, observations for this run, and the reported decision.",
    output:
      "A cited assessment of whether the recorded decision follows the identified clause.",
    whenToUse: "When both a result and its applicable method are supplied.",
    instructions: playbooks["method-adherence"],
    evaluate: methodAdherence,
  },
  {
    id: "repeat-comparison",
    name: "Repeat comparison",
    family: "Evidence & reproducibility",
    stage: "repeat",
    description:
      "Check a repeat against its original observation and the authorized change.",
    input:
      "Linked original and repeat records, comparable measurements and the authorized change.",
    output:
      "A comparison of expected and observed changes with citations and unresolved differences.",
    whenToUse: "When a repeat or remeasurement is linked to an earlier result.",
    instructions: playbooks["repeat-comparison"],
    evaluate: repeatComparison,
  },
];
