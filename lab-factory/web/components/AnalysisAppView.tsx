"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { readAnalysisResult } from "../lib/analysis.ts";
import type { AnalysisResult } from "../lib/analysis.ts";
import { syntheticReadings } from "../lib/readings.ts";
import { expectedLabel, foundLabel, referencePassed } from "../lib/reference.ts";
import type { AnalysisApp } from "../lib/types.ts";
import { CodeBlock } from "./CodeBlock.tsx";
import { runError, useRunner } from "./RunnerContext.tsx";

const UNREADABLE = "The analysis app returned something that isn't a result.";

/**
 * The analysis app: its summary, its code and its reference cases. On first open each case's
 * synthetic readings run through the same code, one after another, in the browser; the answers are
 * kept while the tab stays mounted (mount it keyed by the app, so a different app starts afresh).
 * A runtime failure shows its message with `Try again`, which runs the cases still without an answer.
 */
export function AnalysisAppView({ app }: { app: AnalysisApp }) {
  const run = useRunner();
  const uid = useId();
  const [found, setFound] = useState<(AnalysisResult | null)[]>(() => app.reference_cases.map(() => null));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef(0);
  const foundRef = useRef(found);
  const latest = useRef({ app, run });
  latest.current = { app, run };

  async function runCases() {
    const { app, run } = latest.current;
    const mine = ++attempt.current;
    setRunning(true);
    setError(null);
    for (let i = 0; i < app.reference_cases.length; i += 1) {
      if (foundRef.current[i]) continue;
      try {
        const value = await run(app.code, app.entry, { readings: syntheticReadings(app.reference_cases[i].input) });
        if (mine !== attempt.current) return;
        const result = readAnalysisResult(value);
        if (!result) throw new Error(UNREADABLE);
        setFound((prev) => prev.map((r, j) => (j === i ? result : r)));
        foundRef.current = foundRef.current.map((r, j) => (j === i ? result : r));
      } catch (e) {
        if (mine !== attempt.current) return;
        setError(runError(e));
        setRunning(false);
        return;
      }
    }
    if (mine === attempt.current) setRunning(false);
  }

  // Once, on first open. Unmounting drops the answer of a run still in flight.
  useEffect(() => {
    void runCases();
    return () => { attempt.current += 1; };
  }, []);

  const finished = found.every((r) => r !== null);
  const passedCount = app.reference_cases.filter((c, i) => {
    const result = found[i];
    return result !== null && referencePassed(c, result);
  }).length;
  const doneLine = finished && found.length > 0 ? `Reference cases done: ${passedCount} of ${found.length} passed.` : "";

  return (
    <div className="compute">
      <h2 className="panel-heading">Analysis app</h2>
      <p className="compute-summary">{app.summary}</p>
      <CodeBlock code={app.code} label="Analysis app code" />
      <section className="compute-section" aria-labelledby={`${uid}-title`}>
        <h3 id={`${uid}-title`} className="compute-subhead">Reference cases</h3>
        <p className="compute-note">Each case runs this code in your browser on readings made for it.</p>
        <p role="status" className="compute-status">{running ? "Running in your browser…" : doneLine}</p>
        {error && (
          <div className="compute-error">
            <p role="alert" className="pg-error">{error}</p>
            <button type="button" className="ws-button" onClick={() => void runCases()}>Try again</button>
          </div>
        )}
        <div className="compute-table-wrap">
          <table className="compute-table">
            <caption className="visually-hidden">Reference cases</caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Expected</th>
                <th scope="col">Found</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {app.reference_cases.map((c, i) => {
                const result = found[i];
                const passed = result ? referencePassed(c, result) : null;
                return (
                  <tr key={`${c.name}-${i}`}>
                    <th scope="row">{c.name}</th>
                    <td>{expectedLabel(c)}</td>
                    <td className={result ? undefined : "compute-pending"}>{result ? foundLabel(result) : "Not run yet"}</td>
                    <td className={passed === null ? "compute-pending" : "compute-result"} data-passed={passed === null ? undefined : String(passed)}>
                      {passed === null ? "Not run yet" : (
                        <>
                          {passed
                            ? <CircleCheck size={16} aria-hidden="true" className="compute-icon" />
                            : <CircleX size={16} aria-hidden="true" className="compute-icon" />}
                          <span>{passed ? "Passed" : "Failed"}</span>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
