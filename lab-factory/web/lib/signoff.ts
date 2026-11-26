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

/** A function guarded by `singleFlight`, and whether its last call is still running. */
export type SingleFlight<A extends unknown[], R> = ((...args: A) => Promise<R>) & { busy: () => boolean };

/**
 * Guards `fn` so only one call runs at a time. A call made while one is running does not call `fn`;
 * it gets the running call's promise, so every caller sees the same outcome, value or rejection.
 * The guard is taken before `fn` starts and released once it settles, either way.
 */
export function singleFlight<A extends unknown[], R>(fn: (...args: A) => Promise<R>): SingleFlight<A, R> {
  let running: Promise<R> | null = null;
  const guarded = (...args: A): Promise<R> => {
    if (running) return running;
    let started: Promise<R>;
    try {
      started = fn(...args);
    } catch (e) {
      started = Promise.reject(e);
    }
    const current = started.finally(() => { if (running === current) running = null; });
    running = current;
    return current;
  };
  return Object.assign(guarded, { busy: () => running !== null });
}
