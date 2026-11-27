// Run-local evidence supplied to a read-only, deterministic reviewer.
export type Family =
  | "Lab knowledge"
  | "Experiment planning"
  | "Instruments & execution"
  | "Analysis & results"
  | "Scientific review"
  | "Evidence & reproducibility";
export type Stage = "start" | "result" | "repeat";
export type Verdict = "clear" | "finding" | "unassessed";
export type Finding = {
  verdict: Verdict;
  finding: string;
  references: string[];
};
export type ReviewInput = {
  evidencePacket?: import("./evidence").EvidencePacket;
  runNumber: number;
  kind: "b12" | "time-course";
  mode: "original" | "repeat";
  objective?: string;
  project?: string;
  methodName?: string;
  methodRevision?: string;
  wavelengthNm?: number;
  instrument?: string;
  readings: { x: number; y: number }[];
  sampleAU?: number;
  // undefined means missing evidence; null means concentration explicitly withheld.
  reportedConcentration?: number | null;
  dilutionFactor?: number;
  approvedDilutionFactor?: number;
  original?: { runNumber: number; sampleAU?: number; outcome: string };
};
export type ResearchSkill = {
  id: string;
  name: string;
  family: Family;
  stage: Stage;
  description: string;
  input: string;
  output: string;
  whenToUse: string;
  instructions: string;
  // Return null if inapplicable to this experiment. Findings are advisory.
  evaluate: (input: ReviewInput) => Finding | null;
};
