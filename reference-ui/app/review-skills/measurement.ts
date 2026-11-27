import type { Finding, ResearchSkill, ReviewInput } from "./types";

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function runReference(run: ReviewInput) {
  return Number.isInteger(run.runNumber)
    ? `Run ${run.runNumber}`
    : "Run record";
}

function instrumentRecord(run: ReviewInput): Finding | null {
  if (run.kind !== "b12" && run.kind !== "time-course") return null;

  const instrument = run.instrument?.trim();
  const method = run.methodName?.trim();
  const wavelength = run.wavelengthNm;
  const references = [runReference(run)];
  const missing: string[] = [];
  if (
    instrument &&
    !/^(unknown|unspecified|unassigned|n\/a|tbd|none|instrument)$/i.test(
      instrument,
    )
  ) {
    references.push(`Instrument · ${instrument}`);
  } else {
    missing.push("an identifiable instrument");
  }
  if (method) references.push(`Method · ${method}`);
  else missing.push("a named measurement method");
  if (finite(wavelength) && wavelength > 0)
    references.push(`Wavelength · ${wavelength} nm`);
  else missing.push("a finite, positive wavelength");

  if (missing.length) {
    return {
      verdict: "unassessed",
      finding: `The start record needs ${missing.join(", ")}.`,
      references,
    };
  }
  return {
    verdict: "clear",
    finding: `${instrument} is recorded for ${method} at ${wavelength} nm.`,
    references,
  };
}

function dilutionCalculation(run: ReviewInput): Finding | null {
  if (run.kind !== "b12" || run.mode !== "repeat") return null;

  const { readings, sampleAU, dilutionFactor, reportedConcentration } = run;
  const references = [runReference(run)];
  const review = (verdict: Finding["verdict"], finding: string): Finding => ({
    verdict,
    finding,
    references,
  });
  if (!finite(sampleAU))
    return review(
      "unassessed",
      "A finite repeat sample absorbance is required.",
    );
  references.push(`Repeat sample · ${sampleAU} AU`);
  if (!Array.isArray(readings) || readings.length < 2) {
    return review(
      "unassessed",
      "At least two calibration standards are required.",
    );
  }
  // Keep each standard's original row number when ordering points by absorbance.
  const points = Array.from(readings, (point, i) => ({ ...point, row: i + 1 }));
  const invalid = points.find((p) => !finite(p.x) || !finite(p.y));
  if (invalid) {
    references.push(`Calibration standard ${invalid.row}`);
    return review(
      "unassessed",
      "The calibration includes a missing or nonfinite value.",
    );
  }
  points.sort((a, b) => a.y - b.y);
  const first = points[0];
  const last = points[points.length - 1];
  const direction = Math.sign(last.x - first.x);
  const standard = (p: typeof first) =>
    `Standard ${p.row} · ${p.x} µM at ${p.y} AU`;
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1],
      current = points[i];
    if (
      previous.y === current.y ||
      !direction ||
      Math.sign(current.x - previous.x) !== direction
    ) {
      references.push(standard(previous), standard(current));
      return review(
        "unassessed",
        "The standards do not define a strictly monotonic calibration.",
      );
    }
  }

  if (finite(reportedConcentration))
    references.push(`Reported concentration · ${reportedConcentration} µM`);
  if (reportedConcentration === null)
    references.push("Reported concentration · withheld");
  if (sampleAU < first.y || sampleAU > last.y) {
    references.push(standard(first), standard(last));
    const reason = `The sample is outside the measured range of ${first.y}–${last.y} AU.`;
    if (reportedConcentration === null)
      return review("clear", `${reason} Concentration was withheld.`);
    if (finite(reportedConcentration))
      return review(
        "finding",
        `${reason} Withhold the reported concentration.`,
      );
    return review(
      "unassessed",
      `${reason} The record does not establish whether concentration was withheld.`,
    );
  }

  const upperIndex = points.findIndex((p) => p.y >= sampleAU);
  const upper = points[upperIndex];
  let interpolated = upper.x;
  if (upper.y !== sampleAU) {
    const lower = points[upperIndex - 1];
    references.push(standard(lower));
    const fraction = (sampleAU - lower.y) / (upper.y - lower.y);
    interpolated = lower.x + fraction * (upper.x - lower.x);
    if (!Number.isFinite(upper.y - lower.y)) {
      return review(
        "unassessed",
        "The calibration interval exceeds the finite calculation range.",
      );
    }
  }
  references.push(standard(upper));
  if (!finite(dilutionFactor) || dilutionFactor <= 0) {
    return review(
      "unassessed",
      "A finite, positive recorded dilution factor is required.",
    );
  }
  references.push(`Recorded dilution factor · ${dilutionFactor}×`);
  const corrected = interpolated * dilutionFactor;
  if (!finite(corrected))
    return review(
      "unassessed",
      "The corrected concentration exceeds the finite calculation range.",
    );
  if (!finite(reportedConcentration))
    return review(
      "unassessed",
      "A finite reported concentration is required for comparison.",
    );

  // Allow numerical roundoff in the interpolation and multiplication.
  const tolerance =
    16 *
    Number.EPSILON *
    Math.max(Math.abs(corrected), Math.abs(reportedConcentration));
  const matches = Math.abs(corrected - reportedConcentration) <= tolerance;
  const display = (n: number) => Number(n.toPrecision(15));
  return review(
    matches ? "clear" : "finding",
    `The repeat gives ${display(interpolated)} µM × ${dilutionFactor} = ${display(corrected)} µM. The reported ${reportedConcentration} µM ${matches ? "agrees" : "differs"}.`,
  );
}

export const measurementSkills: ResearchSkill[] = [
  {
    id: "instrument-record",
    name: "Instrument record",
    family: "Instruments & execution",
    stage: "start",
    description:
      "Check whether the start record identifies the instrument and its measurement context.",
    input: "Run instrument, method name and measurement wavelength.",
    output: "A cited start-record check identifying any missing context.",
    whenToUse:
      "At the start of an original or repeat simulated absorbance run.",
    instructions:
      "Read the instrument label, method and wavelength from this run. Cite the supplied fields. Mark the check unassessed if the instrument is unidentified or the method or positive wavelength is missing.",
    evaluate: instrumentRecord,
  },
  {
    id: "dilution-calculation",
    name: "Dilution calculation",
    family: "Analysis & results",
    stage: "repeat",
    description:
      "Check a repeat concentration against the measured calibration and recorded dilution.",
    input:
      "Repeat sample absorbance, standard concentrations and absorbances, recorded dilution factor and reported concentration.",
    output:
      "A cited comparison or a determination that concentration should be withheld.",
    whenToUse: "When reviewing a repeat simulated B12 concentration result.",
    instructions:
      "Confirm the standards define a monotonic calibration. Interpolate between the standards bracketing the repeat absorbance, multiply by the recorded dilution factor and compare with the report. Cite the supporting values. Outside the measured range, check for explicit withholding and flag any numeric report. Mark missing or unusable evidence unassessed.",
    evaluate: dilutionCalculation,
  },
];
