"use client";

import { ChartSpline, Code, FileText, SquareTerminal } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { OutputKind, OutputRef } from "../lib/types.ts";
import { OUTPUT_LABEL } from "./OutputPanel.tsx";

const ICON: Record<OutputKind, LucideIcon> = {
  procedure: FileText,
  run_plan: SquareTerminal,
  analysis_app: Code,
  simulation: ChartSpline,
};

/** A link-like row to an output the factory built: its label and one-line status. Opens the panel on it. */
export function OutputRefCard({ output, onOpen }: { output: OutputRef; onOpen: (kind: OutputKind) => void }) {
  const Icon = ICON[output.kind];
  return (
    <button type="button" className="conv-ref" onClick={() => onOpen(output.kind)}>
      <Icon size={18} aria-hidden="true" className="conv-ref-icon" />
      <span className="conv-ref-label">{OUTPUT_LABEL[output.kind]}</span>
      <span className="conv-ref-summary">{output.summary}</span>
    </button>
  );
}
