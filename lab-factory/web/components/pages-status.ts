// Small display helpers shared by the Task 9 views.
// statusLine here is a local stand-in: Task 12's lib/status.ts replaces it with the real one.
import type { AttentionItem, Document, OrderView, StepView } from "../lib/types.ts";

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** The status line of a procedure; `No procedure yet` when there is none. */
export function procedureStatusLine(procedure: OrderView<StepView> | undefined): string {
  if (!procedure) return "No procedure yet";
  const { order, history } = procedure;
  const last = history[history.length - 1];
  switch (order.status) {
    case "in_progress": return "Being revised";
    case "in_review": return "Waiting for sign-off";
    case "released": {
      const approved = [...history].reverse().find((h) => h.event === "approved");
      return approved ? `Signed off by ${approved.actor} on ${formatDate(approved.at)}` : "Signed off";
    }
    default:
      if (last && last.event === "rejected") return `Rejected by ${last.actor}: ${last.note}`;
      return "Not started";
  }
}

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
