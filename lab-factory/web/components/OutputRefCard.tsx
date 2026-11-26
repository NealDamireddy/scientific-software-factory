"use client";

import { ChartSpline, Code, FileText, SquareTerminal } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { OutputKind, OutputRef } from "../lib/types.ts";
import { outputLabel } from "../lib/status.ts";

const ICON: Record<OutputKind, LucideIcon> = {
  procedure: FileText,
  run_plan: SquareTerminal,
  analysis_app: Code,
  simulation: ChartSpline,
};

/**
 * A link-like row to an output the factory built: its label and one-line status. Opens the panel on it,
 * on the named work order's latest submission when it names one.
 */
export function OutputRefCard({ output, onOpen }: { output: OutputRef; onOpen: (output: OutputRef) => void }) {
  const Icon = ICON[output.kind];
  return (
    <button type="button" className="conv-ref" onClick={() => onOpen(output)}>
      <Icon size={18} aria-hidden="true" className="conv-ref-icon" />
      <span className="conv-ref-label">{outputLabel(output.kind)}</span>
      <span className="conv-ref-summary">{output.summary}</span>
    </button>
  );
}
