"use client";

import { useId } from "react";

import type { RunStepView } from "../lib/types.ts";
import { SettingStrips, StepFailures } from "./ProcedureView.tsx";

export type RunPlanViewProps = {
  /** The steps of the shown submission. Task 13 passes another submission's steps here. */
  steps: RunStepView[];
};

/** A run plan as instrument command lines, each with its settings on range strips and its failing checks. */
export function RunPlanView({ steps }: RunPlanViewProps) {
  const noteId = useId();
  return (
    <div className="proc">
      <div className="proc-send">
        <button type="button" className="ws-button" disabled aria-describedby={noteId}>Send to instrument</button>
        <p id={noteId} className="proc-send-note">Instruments are controlled by the instrument agent, which comes later.</p>
      </div>
      <ol className="proc-steps" aria-label="Steps">
        {steps.map((step) => (
          <li key={step.number} className="proc-step">
            <span className="proc-num">{step.number}</span>
            <div className="proc-body">
              <p className="proc-text">
                <code className="proc-command">{`${step.instrument_id}  ${step.command}`}</code>
              </p>
              <SettingStrips settings={step.settings} />
              <StepFailures failures={step.failures} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
