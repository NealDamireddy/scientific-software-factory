"use client";

import { createContext, useContext, useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";

import { createPythonRunner } from "../lib/runtime/runner.ts";
import type { PythonRunner } from "../lib/runtime/runner.ts";

/** Runs Python in the page's one worker. Rejections carry messages ready to show. */
export type Run = (code: string, entry: string, args: unknown) => Promise<unknown>;

const RunnerContext = createContext<Run | null>(null);

/**
 * One Python runner for everything below it, created on the first run (never while rendering or
 * prerendering, so no Worker starts until someone runs code) and disposed on unmount. A runner whose
 * worker failed starts a fresh one on the next run, so a retry works.
 */
export function RunnerProvider({ children }: { children: ReactNode }) {
  const runner = useRef<PythonRunner | null>(null);

  useEffect(() => () => {
    runner.current?.dispose();
    runner.current = null;
  }, []);

  const run = useMemo<Run>(() => (code, entry, args) => {
    if (!runner.current) runner.current = createPythonRunner();
    return runner.current.run(code, entry, args);
  }, []);

  return <RunnerContext.Provider value={run}>{children}</RunnerContext.Provider>;
}

export function useRunner(): Run {
  const run = useContext(RunnerContext);
  if (!run) throw new Error("useRunner() needs a <RunnerProvider> above it.");
  return run;
}

/** The message to show for a failed run: the runner's own words, or a plain fallback. */
export function runError(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "The analysis failed.";
}
