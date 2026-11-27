// Small display helpers shared by the lab, project and settings pages. Status lines live in lib/status.ts.
import type { Document } from "../lib/types.ts";

export { errorText, formatDate } from "../lib/status.ts";

export const DOCUMENT_KINDS: { value: Document["kind"]; label: string }[] = [
  { value: "sop", label: "SOP" },
  { value: "manual", label: "Manual" },
  { value: "standard", label: "Standard" },
  { value: "paper", label: "Paper" },
  { value: "note", label: "Note" },
];

export function kindLabel(kind: Document["kind"]): string {
  return DOCUMENT_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

/** `integration_time` becomes `Integration time`. */
export function sentenceCase(name: string): string {
  const text = name.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
