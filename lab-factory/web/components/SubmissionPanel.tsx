"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import { choiceKey, citedSources, latestChoice, submissionOptions } from "../lib/history.ts";
import { unplacedFailures } from "../lib/status.ts";
import type { CheckResult, OrderView, RunStepView, StepView } from "../lib/types.ts";
import { ClientError } from "../lib/types.ts";
import { BuiltFrom } from "./BuiltFrom.tsx";
import { useClient } from "./ClientContext.tsx";
import { SubmissionDiff } from "./SubmissionDiff.tsx";
import { SubmissionHeader } from "./SubmissionHeader.tsx";
import { SubmissionPicker } from "./SubmissionPicker.tsx";

export type SubmissionPanelProps<S extends StepView | RunStepView> = {
  kind: "procedure" | "run_plan";
  experimentId: string;
  view: OrderView<S>;
  /** Renders the shown submission's steps. */
  renderSteps: (steps: S[], unplaced: CheckResult[]) => ReactNode;
};

type Picked = { resetKey: string; key: string };
type Loaded<S> = { key: string; steps: S[] } | { key: string; error: string };

/**
 * A procedure or run plan tab's body: the header for the shown submission with the picker and Compare,
 * the comparison when open, the shown submission's steps and "Built from". The shown submission is the
 * newest order's latest unless the person picks another; the choice resets when the experiment or the
 * newest order changes.
 */
export function SubmissionPanel<S extends StepView | RunStepView>({ kind, experimentId, view, renderSteps }: SubmissionPanelProps<S>) {
  const { client, version } = useClient();
  const hintId = useId();
  const picker = useRef<HTMLSelectElement>(null);
  const compareButton = useRef<HTMLButtonElement>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [comparing, setComparing] = useState(false);
  const [loaded, setLoaded] = useState<Loaded<S> | null>(null);

  const options = submissionOptions(view);
  const latest = latestChoice(view);
  const latestKey = choiceKey(latest);
  const resetKey = `${experimentId}\n${view.order.id}`;
  const chosenKey = picked && picked.resetKey === resetKey && options.some((o) => o.key === picked.key) ? picked.key : latestKey;
  const isLatest = chosenKey === latestKey;
  const shown = options.find((o) => o.key === chosenKey);
  const fetchOrder = isLatest || !shown ? null : shown.record.order.id;
  const fetchNumber = isLatest || !shown ? null : shown.submission.number;

  useEffect(() => {
    if (fetchOrder === null || fetchNumber === null) return;
    const key = choiceKey({ workOrderId: fetchOrder, number: fetchNumber });
    let live = true;
    client.getSubmissionView(fetchOrder, fetchNumber).then(
      (result) => { if (live) setLoaded({ key, steps: result.steps as S[] }); },
      (e: unknown) => {
        if (live) setLoaded({ key, error: e instanceof ClientError ? e.message : "Couldn't load that submission." });
      },
    );
    return () => { live = false; };
  }, [client, fetchOrder, fetchNumber, version]);

  const current = !isLatest && loaded && loaded.key === chosenKey ? loaded : null;
  const steps: S[] | null = isLatest ? view.steps : current && "steps" in current ? current.steps : null;
  const loadError = current && "error" in current ? current.error : null;

  function choose(key: string) {
    setPicked({ resetKey, key });
  }

  function backToLatest() {
    setPicked(null);
    picker.current?.focus();
  }

  function closeComparison() {
    setComparing(false);
    compareButton.current?.focus();
  }

  const canCompare = options.length > 1 && shown !== undefined;
  const hint = options.length > 0 && !canCompare
    ? <p id={hintId} className="hist-hint">Nothing to compare yet.</p>
    : null;
  const earlier = !isLatest && shown ? (
    <p className="hist-earlier">
      <span>You&apos;re viewing an earlier submission.</span>
      <button type="button" className="ws-button hist-quiet" onClick={backToLatest}>Back to the latest</button>
    </p>
  ) : null;
  const note = hint || earlier ? <>{hint}{earlier}</> : undefined;

  return (
    <>
      <SubmissionHeader
        order={shown ? shown.record.order : view.order}
        submission={shown?.submission}
        history={shown ? shown.record.history : view.history}
        note={note}
      >
        {options.length > 0 && (
          <>
            <SubmissionPicker
              ref={picker}
              options={options}
              value={chosenKey}
              onChange={choose}
              pending={shown ? undefined : `${view.order.id}, nothing submitted yet`}
            />
            <button
              ref={compareButton}
              type="button"
              className="ws-button hist-quiet hist-compare"
              aria-expanded={canCompare ? comparing : undefined}
              aria-describedby={canCompare ? undefined : hintId}
              disabled={!canCompare}
              onClick={() => setComparing((open) => !open)}
            >
              Compare
            </button>
          </>
        )}
        {/* Task 15: <SignOff order submission /> mounts here, only while isLatest. */}
      </SubmissionHeader>
      {comparing && canCompare && shown && (
        <SubmissionDiff key={shown.key} kind={kind} shown={shown} options={options} onClose={closeComparison} />
      )}
      {loadError && <p role="alert" className="pg-error hist-load-error">{loadError}</p>}
      {shown && !steps && !loadError && <p role="status" className="hist-loading">Loading submission {shown.submission.number}…</p>}
      {shown && steps && (
        <>
          {renderSteps(steps, unplacedFailures(shown.submission.results, steps))}
          <BuiltFrom
            order={shown.record.order}
            submission={shown.submission}
            history={shown.record.history}
            sources={citedSources(steps as { sources?: { id: string; title: string }[] }[])}
          />
        </>
      )}
    </>
  );
}
