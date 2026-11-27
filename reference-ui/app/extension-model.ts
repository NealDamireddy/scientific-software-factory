export type Harness = { name: string; endpoint: string };
type Connector = { id: string; name: string; description: string };
export type CustomConnector = Connector & { endpoint: string };
export type CustomSkill = {
  id: string;
  name: string;
  whenToUse: string;
  instructions: string;
};

export type ExtensionState = {
  harness: Harness | null;
  connectors: string[];
  skills: string[];
  customConnectors: CustomConnector[];
  customSkills: CustomSkill[];
};

export const builtinConnectors: Connector[] = [
  {
    id: "notebook",
    name: "Lab notebook",
    description:
      "Protocol notes and sample annotations from a shared notebook.",
  },
  {
    id: "archive",
    name: "Instrument archive",
    description: "Measurement files and instrument run records.",
  },
];

export const builtinSkills = [
  {
    id: "calibration",
    name: "Calibration review",
    description: "Check sample readings against a calibration range.",
    input: "Calibration standards and sample absorbance",
    output: "Range assessment and a review note",
    whenToUse:
      "When reviewing a simulated sample measured against calibration standards.",
    instructions:
      "Identify the measured range and units from the supplied standards. Compare the original and repeat sample readings with that range. Withhold a concentration for any out-of-range reading. For an in-range repeat, report the recorded dilution factor and explain how it affects the reported concentration. Identify missing inputs and reference the run for each observation.",
  },
  {
    id: "evidence",
    name: "Evidence summary",
    description: "Summarize the records behind an experiment result.",
    input: "Run history, source readings, and reviewer decisions",
    output: "A summary with references to the underlying records",
    whenToUse:
      "When tracing a simulated result to its source records or explaining a review decision.",
    instructions:
      "List the recorded instrument, method revision, source readings, and reviewer decisions in order. Identify each run by its number and preserve the original and repeated readings separately. Summarize which observations support the reported result and identify any missing evidence.",
  },
  {
    id: "method",
    name: "Method comparison",
    description: "Compare two versions of an experimental method.",
    input: "Two method records",
    output: "A list of changes to parameters and interpretation",
    whenToUse:
      "When two recorded versions of a simulated method are available for comparison.",
    instructions:
      "Identify both revision identifiers. Compare recorded parameters field by field, including units, and describe changes that affect interpretation. If a value or revision is missing, mark the comparison incomplete. Reference the two source records in the summary.",
  },
];

export const defaultExtensions: ExtensionState = {
  harness: null,
  connectors: [],
  skills: ["calibration", "evidence"],
  customConnectors: [],
  customSkills: [],
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function isValidEndpoint(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return (
      ["http:", "https:"].includes(url.protocol) &&
      Boolean(url.hostname) &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

function parseHarness(value: unknown): Harness | null {
  const { name, endpoint } = asRecord(value);
  if (typeof name !== "string" || !name.trim() || !isValidEndpoint(endpoint))
    return null;
  return { name, endpoint };
}

function parseConnector(value: unknown): CustomConnector | null {
  const { id, description } = asRecord(value);
  const address = parseHarness(value);
  if (
    !address ||
    typeof id !== "string" ||
    !id.trim() ||
    typeof description !== "string"
  )
    return null;
  return { id, ...address, description };
}

function parseSkill(value: unknown): CustomSkill | null {
  const { id, name, whenToUse, instructions } = asRecord(value);
  if (
    typeof id !== "string" ||
    !id.trim() ||
    typeof name !== "string" ||
    !name.trim() ||
    typeof whenToUse !== "string" ||
    !whenToUse.trim() ||
    typeof instructions !== "string" ||
    !instructions.trim()
  )
    return null;
  return { id, name, whenToUse, instructions };
}

function customRecords<T extends { id: string }>(
  value: unknown,
  builtins: { id: string }[],
  parse: (entry: unknown) => T | null,
): T[] {
  const seen = new Set(builtins.map((item) => item.id));
  const records: T[] = [];
  for (const entry of Array.isArray(value) ? value : []) {
    const record = parse(entry);
    if (record && !seen.has(record.id)) {
      records.push(record);
      seen.add(record.id);
    }
  }
  return records;
}

function enabledIds(
  value: unknown,
  known: { id: string }[],
  fallback: string[],
): string[] {
  const ids = new Set(known.map((item) => item.id));
  return Array.from(
    new Set(
      (Array.isArray(value) ? value : fallback).filter(
        (id): id is string => typeof id === "string" && ids.has(id),
      ),
    ),
  );
}

export function normalizeExtensions(value: unknown): ExtensionState {
  const saved = asRecord(value);
  const customConnectors = customRecords(
    saved.customConnectors,
    builtinConnectors,
    parseConnector,
  );
  const customSkills = customRecords(
    saved.customSkills,
    builtinSkills,
    parseSkill,
  );
  return {
    harness: parseHarness(saved.harness),
    connectors: enabledIds(
      saved.connectors,
      [...builtinConnectors, ...customConnectors],
      defaultExtensions.connectors,
    ),
    skills: enabledIds(
      saved.skills,
      [...builtinSkills, ...customSkills],
      defaultExtensions.skills,
    ),
    customConnectors,
    customSkills,
  };
}

export type AgentContext = {
  schemaVersion: 1;
  simulationOnly: true;
  executionAuthority: "none";
  harness: Harness | null;
  connectors: (Connector & { endpoint?: string })[];
  skills: CustomSkill[];
};

export function buildAgentContext(state: ExtensionState): AgentContext {
  const saved = normalizeExtensions(state);
  const connectors = [...builtinConnectors, ...saved.customConnectors];
  const skills = [...builtinSkills, ...saved.customSkills];
  return {
    schemaVersion: 1,
    simulationOnly: true,
    executionAuthority: "none",
    harness: saved.harness,
    connectors: connectors
      .filter((item) => saved.connectors.includes(item.id))
      .map((item) => ({ ...item })),
    skills: skills
      .filter((item) => saved.skills.includes(item.id))
      .map(({ id, name, whenToUse, instructions }) => ({
        id,
        name,
        whenToUse,
        instructions,
      })),
  };
}
