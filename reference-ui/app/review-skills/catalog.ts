import { evidenceSkills } from "./evidence.ts";
import { planningSkills } from "./planning.ts";
import { measurementSkills } from "./measurement.ts";
import { reviewSkills } from "./review.ts";
import type { ResearchSkill } from "./types";

export const researchSkills: ResearchSkill[] = [
  ...planningSkills,
  ...measurementSkills,
  ...reviewSkills,
  ...evidenceSkills,
];
