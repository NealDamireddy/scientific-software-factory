import type { Finding, ResearchSkill, ReviewInput } from "./types";

export type EvidencePacket = {
  source: string;
  observations: {
    row: number;
    sample: string;
    measurement: string;
    value: number | null;
    unit: string;
  }[];
  claim?: {
    sample: string;
    measurement: string;
    value: number;
    unit: string;
    statistic?: "mean";
  };
};
type Observation = EvidencePacket["observations"][number];
type PacketReviewer = (packet: EvidencePacket) => Finding;

const text = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const validRow = (row: unknown): row is number =>
  typeof row === "number" && Number.isSafeInteger(row) && row > 0;
const number = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
const result = (
  verdict: Finding["verdict"],
  finding: string,
  references: string[],
): Finding => ({ verdict, finding, references });
const unavailable = (why: string, refs: string[] = []) =>
  result("unassessed", why, refs);

function rowRef(source: string, observation: Observation): string {
  return `${source} · row ${observation.row}`;
}

function reviewProvenance(packet: EvidencePacket): Finding {
  const source = text(packet?.source);
  if (!source)
    return unavailable(
      "Name the source file or record so its observations can be traced.",
    );
  if (!Array.isArray(packet.observations) || packet.observations.length === 0)
    return unavailable(
      "No observation rows were supplied for provenance review.",
      [source],
    );
  const counts = new Map<number, number>();
  for (const observation of packet.observations) {
    if (validRow(observation?.row))
      counts.set(observation.row, (counts.get(observation.row) ?? 0) + 1);
  }
  const issues: string[] = [];
  const refs = new Set<string>();
  for (const [i, observation] of packet.observations.entries()) {
    const problems: string[] = [];
    const addressable = validRow(observation?.row);
    const label = addressable
      ? `Row ${observation.row}`
      : `Observation ${i + 1}`;
    if (!addressable) problems.push("missing or invalid source row number");
    else if (counts.get(observation.row)! > 1)
      problems.push("repeated source row number");
    if (!text(observation?.sample)) problems.push("missing sample");
    if (!text(observation?.measurement)) problems.push("missing measurement");
    if (!number(observation?.value))
      problems.push("missing or nonfinite value");
    if (!text(observation?.unit)) problems.push("missing unit");
    if (problems.length) {
      issues.push(`${label}: ${problems.join(", ")}.`);
      refs.add(addressable ? rowRef(source, observation) : source);
    }
  }
  if (issues.length) return result("finding", issues.join(" "), [...refs]);
  return result(
    "clear",
    `All ${packet.observations.length} observation rows identify a sample, measurement, finite value, unit and unique source row.`,
    packet.observations.map((o) => rowRef(source, o)),
  );
}

// Express finite binary64 measurements as integer multiples of the smallest
// subnormal. The exact sum survives cancellation and cannot overflow.
function binaryBits(value: number): bigint {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  return view.getBigUint64(0);
}
function arithmeticMean(values: number[]): number {
  let sum = 0n;
  const fractionMask = (1n << 52n) - 1n;
  for (const value of values) {
    const bits = binaryBits(Math.abs(value));
    const exponent = Number(bits >> 52n);
    const fraction = bits & fractionMask;
    const units =
      exponent === 0
        ? fraction
        : ((1n << 52n) | fraction) << BigInt(exponent - 1);
    sum += value < 0 ? -units : units;
  }
  const magnitude = sum < 0n ? -sum : sum;
  const count = BigInt(values.length);
  // Pick the output spacing, then round the exact quotient once, ties to even.
  const shift = Math.max(0, (magnitude / count).toString(2).length - 53);
  const divisor = count << BigInt(shift);
  let rounded = magnitude / divisor;
  const twiceRemainder = (magnitude % divisor) * 2n;
  if (
    twiceRemainder > divisor ||
    (twiceRemainder === divisor && rounded % 2n === 1n)
  )
    rounded += 1n;
  return (sum < 0n ? -1 : 1) * Number(rounded) * 2 ** (shift - 1074);
}
function agreesAtMachinePrecision(claim: number, mean: number) {
  if (claim === mean) return true;
  if (claim === 0 || mean === 0 || Math.sign(claim) !== Math.sign(mean))
    return false;
  const delta = binaryBits(Math.abs(claim)) - binaryBits(Math.abs(mean));
  return delta === 1n || delta === -1n;
}

function reviewMean(
  packet: EvidencePacket,
  group: Observation[],
  refs: string[],
): Finding {
  const claim = packet.claim!;
  if (group.length < 2)
    return unavailable(
      `The mean requires at least two observations for ${text(claim.sample)}, ${text(claim.measurement)}. Found ${group.length}.`,
      refs,
    );
  const rowCounts = new Map<number, number>();
  for (const observation of packet.observations) {
    if (validRow(observation?.row))
      rowCounts.set(observation.row, (rowCounts.get(observation.row) ?? 0) + 1);
  }
  const values: number[] = [];
  for (const o of group) {
    if (!validRow(o.row) || rowCounts.get(o.row) !== 1)
      return unavailable(
        "The mean requires a unique, traceable source row number for every group observation.",
        refs,
      );
    if (text(o.unit) !== text(claim.unit))
      return unavailable(
        `Row ${o.row} has a missing or incompatible unit. All ${group.length} group observations must use ${text(claim.unit)}.`,
        refs,
      );
    if (!number(o.value))
      return unavailable(
        `Row ${o.row} lacks a finite value. All ${group.length} group observations are required to calculate the mean.`,
        refs,
      );
    values.push(o.value);
  }
  const mean = arithmeticMean(values);
  return result(
    agreesAtMachinePrecision(claim.value, mean) ? "clear" : "finding",
    `Arithmetic mean of ${values.length} observations for ${text(claim.sample)}, ${text(claim.measurement)}. Calculated ${mean} ${text(claim.unit)}, claimed ${claim.value} ${text(claim.unit)}.`,
    refs,
  );
}

function reviewClaim(packet: EvidencePacket): Finding {
  const source = text(packet?.source);
  if (!source) return unavailable("The claim needs a named evidence source.");
  const claim = packet.claim;
  if (!claim)
    return unavailable("No numeric claim was supplied for comparison.", [
      source,
    ]);
  const sample = text(claim.sample),
    measurement = text(claim.measurement),
    unit = text(claim.unit);
  if (!sample || !measurement || !unit || !number(claim.value))
    return unavailable(
      "The claim needs a sample, measurement, finite value and unit.",
      [source],
    );
  if (!Array.isArray(packet.observations) || !packet.observations.length)
    return unavailable("No observations were supplied for comparison.", [
      source,
    ]);
  const candidates = packet.observations.filter(
    (o) => text(o?.sample) === sample && text(o?.measurement) === measurement,
  );
  const matches = candidates.filter((o) => text(o.unit) === unit);
  const references = (rows: Observation[]) => [
    ...new Set(rows.map((o) => (validRow(o.row) ? rowRef(source, o) : source))),
  ];
  if (claim.statistic === "mean") {
    return reviewMean(
      packet,
      candidates,
      candidates.length ? references(candidates) : [source],
    );
  }
  if (claim.statistic !== undefined)
    return unavailable("The supplied statistic is unsupported.", [source]);
  if (!matches.length) {
    if (candidates.length)
      return unavailable(
        `The recorded rows for ${sample}, ${measurement} have no matching unit (${unit}).`,
        references(candidates),
      );
    return unavailable(
      `No row identifies both sample ${sample} and measurement ${measurement}.`,
      [source],
    );
  }
  if (matches.length > 1)
    return unavailable(
      `${matches.length} rows match ${sample}, ${measurement} in ${unit}. A unique observation is required.`,
      references(matches),
    );
  const observation = matches[0];
  if (!validRow(observation.row))
    return unavailable(
      "The matching observation has no usable source row number.",
      [source],
    );
  const refs = [rowRef(source, observation)];
  if (
    packet.observations.filter((o) => o?.row === observation.row).length !== 1
  )
    return unavailable(
      "The matching observation shares its source row number with another record.",
      refs,
    );
  if (!number(observation.value))
    return unavailable(
      "The matching observation has no finite numeric value.",
      refs,
    );
  const detail = `${sample}, ${measurement}: claimed ${claim.value} ${unit}; recorded ${observation.value} ${unit}.`;
  return result(
    claim.value === observation.value ? "clear" : "finding",
    detail,
    refs,
  );
}

function reviewRun(reviewer: PacketReviewer, input: ReviewInput): Finding {
  if (input.evidencePacket) return reviewer(input.evidencePacket);
  const refs = validRow(input.runNumber)
    ? [`Run ${input.runNumber} · run record`]
    : [];
  return unavailable("This run has no supplied observation packet.", refs);
}

export const evidenceSkills: ResearchSkill[] = [
  {
    id: "data-provenance",
    name: "Data intake and provenance",
    family: "Evidence & reproducibility",
    stage: "result",
    description:
      "Trace observations to sources and assess how gaps or corrections affect the claim.",
    input:
      "Original observations, identity keys, units and any source-linked corrections.",
    output: "Traceable conclusions, affected records and unresolved attribution.",
    whenToUse: "When reviewing observations from a supplied dataset.",
    instructions: `1. Identify the claim and trace its required fields to the records actually supplied. Use the data dictionary and stable source locations to distinguish a subject, event, sample, replicate and reading. Record units, identity links and transformations where they affect interpretation. Preserve the original value and locator alongside any correction.

2. For each missing or disputed field, ask which conclusions depend on it. A reading can support one calculation while its attribution to a particular source remains unresolved. Show which observations enter each conclusion and why. Avoid silently discarding usable measurements or filling missing fields from plausibility.

3. When a note conflicts with a record, inspect its author, timing, scope and the lab’s correction or reconciliation procedure. An authorized, traceable amendment may supersede an earlier field. An unsupported note can justify an investigation. Cite both records, state what survives under either reading, and identify the smallest missing link that would change the decision.`,
    evaluate: (input) => reviewRun(reviewProvenance, input),
  },
  {
    id: "claim-evidence",
    name: "Claim-to-evidence review",
    family: "Scientific review",
    stage: "result",
    description:
      "Review a reported result against the research question, comparison units and underlying measurements.",
    input:
      "The claim, its population and time window, and the underlying observations with identity keys.",
    output:
      "Agreement, disagreement or a missing-evidence assessment with row references.",
    whenToUse:
      "When reviewing a reported result against its underlying individual or group measurements.",
    instructions: `1. Translate the request into a quantity the evidence can answer. Identify the population, unit of observation, unit being compared, time window and intended units. Ask what gets one vote in the calculation. For change over time, determine whether the question concerns the same subjects or the populations observed at each time. State the relevant denominator and exclusions.

2. Trace the claim to its records and independently recompute it. Use identity keys for paired measurements. For grouped records, choose weighting from the research question and documented analysis plan. If two interpretations give materially different answers and the context cannot resolve them, give the conditional results or ask the narrow question that distinguishes them. Keep measured values, derived quantities and assumptions distinguishable.

3. Report what the records support, contradict or leave unresolved. Cite the decisive observations or reproducible selection and the lab context that justifies it. Explain what would change the decision and preserve conclusions unaffected by missing evidence. The local CSV checker covers a direct observation or a single group mean. Broader scientific claims require agent reasoning over the relevant records.`,
    evaluate: (input) => reviewRun(reviewClaim, input),
  },
];

export function reviewEvidencePacket(
  packet: EvidencePacket,
  enabledIds: string[],
): (Finding & { skillId: string })[] {
  const checks: { id: string; review: PacketReviewer }[] = [
    { id: "data-provenance", review: reviewProvenance },
    { id: "claim-evidence", review: reviewClaim },
  ];
  return checks
    .filter((c) => enabledIds.includes(c.id))
    .map((c) => ({ skillId: c.id, ...c.review(packet) }));
}
