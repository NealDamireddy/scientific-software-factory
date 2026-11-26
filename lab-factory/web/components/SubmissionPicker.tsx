"use client";

import { forwardRef, useId } from "react";

import type { SubmissionOption } from "../lib/history.ts";

export type SubmissionPickerProps = {
  /** Every submission across the experiment's orders of this kind, newest first (see `submissionOptions`). */
  options: SubmissionOption[];
  /** The shown submission's key, `{order id}#{n}`. */
  value: string;
  onChange: (key: string) => void;
  /** When the newest order has nothing submitted yet, the label of an entry standing for it. */
  pending?: string;
};

/** A `<select>` labelled `Submission`: `{order id} submission {n}, {summary}`, newest first. */
export const SubmissionPicker = forwardRef<HTMLSelectElement, SubmissionPickerProps>(function SubmissionPicker(
  { options, value, onChange, pending }, ref,
) {
  const id = useId();
  return (
    <span className="hist-field">
      <label htmlFor={id} className="hist-label">Submission</label>
      <select ref={ref} id={id} className="hist-select" value={value} onChange={(e) => onChange(e.target.value)}>
        {pending !== undefined && <option value={value} disabled>{pending}</option>}
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
    </span>
  );
});
