"use client";

import { useEffect, useRef, useState } from "react";

import { readSimulation } from "../lib/analysis.ts";
import type { SimulatedSeries } from "../lib/analysis.ts";
import type { Simulation } from "../lib/types.ts";
import { CodeBlock } from "./CodeBlock.tsx";
import { Plot } from "./Plot.tsx";
import { runError, useRunner } from "./RunnerContext.tsx";

const UNREADABLE = "The simulation returned something that isn't a set of curves.";

type Outcome = { state: "running" } | { state: "done"; series: SimulatedSeries[] } | { state: "error"; message: string; run: number };

/** The simulation extra: what it is, its code, and `Run simulation`, which runs it here and plots its curves. */
export function SimulationView({ simulation }: { simulation: Simulation }) {
  const run = useRunner();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const seq = useRef(0);

  useEffect(() => () => { seq.current += 1; }, []);

  async function simulate() {
    const mine = ++seq.current;
    setOutcome({ state: "running" });
    try {
      const value = await run(simulation.code, simulation.entry, {});
      if (mine !== seq.current) return;
      const series = readSimulation(value);
      setOutcome(series ? { state: "done", series } : { state: "error", message: UNREADABLE, run: mine });
    } catch (e) {
      if (mine === seq.current) setOutcome({ state: "error", message: runError(e), run: mine });
    }
  }

  const busy = outcome?.state === "running";
  return (
    <div className="compute">
      <h2 className="panel-heading">Extra: simulation</h2>
      <h3 className="compute-subhead">{simulation.title}</h3>
      <p className="compute-summary">{simulation.summary}</p>
      <p className="compute-tag compute-tag-line">Sample content</p>
      <CodeBlock code={simulation.code} label="Simulation code" />
      <div className="sim-run">
        <button type="button" className="ws-button sim-button" disabled={busy} onClick={() => void simulate()}>
          Run simulation
        </button>
        <p role="status" className="compute-status">{busy ? "Running in your browser…" : outcome?.state === "done" ? "Simulation done." : ""}</p>
      </div>
      {outcome?.state === "error" && <p key={outcome.run} role="alert" className="pg-error compute-alert">{outcome.message}</p>}
      {outcome?.state === "done" && (
        <Plot
          title={simulation.title}
          xLabel={simulation.x_label}
          yLabel={simulation.y_label}
          series={outcome.series.map((s) => ({ label: s.label, points: s.points, style: "line" as const }))}
        />
      )}
    </div>
  );
}
