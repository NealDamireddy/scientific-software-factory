"use client";

import type { Workspace } from "../../lib/types.ts";
import { SimulationView } from "../SimulationView.tsx";

/** The Simulation tab: the extra simulation, its code and its plot. */
export function SimulationTab({ workspace }: { workspace: Workspace }) {
  const simulation = workspace.simulation;
  if (!simulation) return <h2 className="panel-heading">Extra: simulation</h2>;
  return <SimulationView simulation={simulation} />;
}
