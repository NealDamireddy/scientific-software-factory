import { playbooks } from "./review-skills/playbooks.ts";
import { researchSkills } from "./review-skills/catalog.ts";
import type { ResearchSkill, Family, Stage } from "./review-skills/types";

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

export const builtinSkills: Omit<ResearchSkill, "evaluate">[] = [
  {
    id: "calibration",
    family: "Analysis & results",
    stage: "result",
    name: "Calibration review",
    description:
      "Review calibration range and independent evidence for a reported result.",
    input: "Eligible standards, sample response, applicable method revision and independent checks where relevant",
    output: "Range and check assessments with a decision scoped to the method",
    whenToUse: "When a quantitative result depends on calibration standards.",
    instructions: playbooks["calibration"],
  },
  {
    id: "evidence",
    family: "Evidence & reproducibility",
    stage: "result",
    name: "Evidence summary",
    description:
      "Trace a reported result to its readings, method, and review decisions.",
    input: "Run history, source readings, and reviewer decisions",
    output: "A summary with references to the underlying records",
    whenToUse: "When preparing a record for independent review.",
    instructions: playbooks["evidence"],
  },
  {
    id: "method",
    family: "Scientific review",
    stage: "repeat",
    name: "Method comparison",
    description:
      "Compare the method revisions and settings recorded for two runs.",
    input: "Two method records",
    output: "A list of changes to parameters and interpretation",
    whenToUse: "When a comparison relies on the runs using comparable methods.",
    instructions: playbooks["method"],
  },
  ...researchSkills.map(({ evaluate, ...definition }) => definition),
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
  skills: (CustomSkill & {
    source?: "builtin";
    family?: Family;
    stage?: Stage;
  })[];
};

export function buildAgentContext(state: ExtensionState): AgentContext {
  const saved = normalizeExtensions(state);
  const connectors = [...builtinConnectors, ...saved.customConnectors];
  return {
    schemaVersion: 1,
    simulationOnly: true,
    executionAuthority: "none",
    harness: saved.harness,
    connectors: connectors
      .filter((item) => saved.connectors.includes(item.id))
      .map((item) => ({ ...item })),
    skills: [
      ...builtinSkills
        .filter((skill) => saved.skills.includes(skill.id))
        .map(({ id, name, whenToUse, instructions, family, stage }) => ({
          id,
          name,
          whenToUse,
          instructions,
          family,
          stage,
          source: "builtin" as const,
        })),
      ...saved.customSkills
        .filter((skill) => saved.skills.includes(skill.id))
        .map((skill) => ({ ...skill })),
    ],
  };
}

export type WorkerSkill = {
  id: string;
  name: string;
  whenToUse: string;
  instructions: string;
  stage?: Stage;
};

export function workerSkills(state: ExtensionState): WorkerSkill[] {
  return buildAgentContext(state).skills.map(
    ({ id, name, whenToUse, instructions, stage }) => ({
      id,
      name,
      whenToUse,
      instructions,
      ...(stage ? { stage } : {}),
    }),
  );
}
