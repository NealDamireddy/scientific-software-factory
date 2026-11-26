// The sign-off form's rules, apart from the component: when confirm may be pressed, which names the
// lab's rule offers, and what a refusal says. The client decides; this only presents its answer.
import type { LabSettings } from "./types.ts";

export type SignOffKind = "approve" | "reject";

/** Confirm needs a name, and a reason to reject. Whitespace alone is blank. */
export function canConfirm(kind: SignOffKind, fields: { name: string; reason: string }): boolean {
  if (fields.name.trim() === "") return false;
  return kind === "approve" || fields.reason.trim() !== "";
}

/** The names to choose from under a listed rule; null means the person types their name. */
export function nameChoices(settings: LabSettings | null): string[] | null {
  return settings && settings.sign_off.mode === "listed" ? settings.sign_off.names : null;
}

const FALLBACK = "The sign-off didn't go through. Try again.";

/** What the form's alert says when approve or reject fails: the client's own words (the rule or stale refusal). */
export function signOffMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : FALLBACK;
}
