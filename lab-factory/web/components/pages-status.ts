// Small display helpers shared by the lab, project and settings pages. Status lines live in lib/status.ts.
import type { AttentionItem, Document } from "../lib/types.ts";

export { formatDate } from "../lib/status.ts";

export const ATTENTION_TEXT: Record<AttentionItem["kind"], string> = {
  sign_off: "Waiting for sign-off",
  signed_off: "Signed off",
  rejected: "Rejected",
};

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

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
