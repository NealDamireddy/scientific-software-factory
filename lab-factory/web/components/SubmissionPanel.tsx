"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import { choiceKey, citedSources, latestChoice, submissionOptions } from "../lib/history.ts";
import type { SubmissionOption } from "../lib/history.ts";
import { unplacedFailures } from "../lib/status.ts";
import type { CheckResult, OrderView, RunStepView, StepView } from "../lib/types.ts";
import { ClientError } from "../lib/types.ts";
import { BuiltFrom } from "./BuiltFrom.tsx";
import { useClient } from "./ClientContext.tsx";
import { SignOff } from "./SignOff.tsx";
import { SubmissionDiff } from "./SubmissionDiff.tsx";
import { SubmissionHeader } from "./SubmissionHeader.tsx";
import { SubmissionPicker } from "./SubmissionPicker.tsx";

/**
 * A request, from elsewhere in the workspace, to show an order's latest submission: an output card
 * in the conversation that names its work order. A new `nonce` makes the same request again.
 */
export type ShowOrderRequest = { kind: "procedure" | "run_plan"; workOrderId: string; nonce: number };

export type SubmissionPanelProps<S extends StepView | RunStepView> = {
  kind: "procedure" | "run_plan";
  experimentId: string;
  view: OrderView<S>;
  /** Renders the shown submission's steps. */
  renderSteps: (steps: S[], unplaced: CheckResult[]) => ReactNode;
  request?: ShowOrderRequest | null;
};

type Picked = { resetKey: string; key: string };
type Loaded<S> = { key: string; steps: S[] } | { key: string; error: string };
/** The steps on screen: the shown submission's, or the previous ones (dimmed) while the new ones load. */
type Kept<S> = { key: string; steps: S[]; results: CheckResult[] };

/** The latest submission of the named order, by key. */
function latestOf(options: SubmissionOption[], workOrderId: string): string | null {
  const own = options.filter((o) => o.record.order.id === workOrderId);
  if (own.length === 0) return null;
  return own.reduce((a, b) => (b.submission.number > a.submission.number ? b : a)).key;
}

/**
 * A procedure or run plan tab's body: the header for the shown submission with the picker and Compare,
 * the comparison when open, the shown submission's steps and "Built from". The shown submission is the
 * newest order's latest unless the person picks another; the choice resets when the experiment or the
 * newest order changes.
 */
export function SubmissionPanel<S extends StepView | RunStepView>({ kind, experimentId, view, renderSteps, request }: SubmissionPanelProps<S>) {
  const { client, labId, version } = useClient();
  const hintId = useId();
  const diffId = useId();
  const picker = useRef<HTMLSelectElement>(null);
  const compareButton = useRef<HTMLButtonElement>(null);
  const summary = useRef<HTMLHeadingElement>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [comparing, setComparing] = useState(false);
  const [loaded, setLoaded] = useState<Loaded<S> | null>(null);
  const [kept, setKept] = useState<Kept<S> | null>(null);
  const [skillTitles, setSkillTitles] = useState<ReadonlyMap<string, string> | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);
  const [consumed, setConsumed] = useState<number | null>(null);
  // While a sign-off is in progress the shown submission stays put.
  const [signing, setSigning] = useState(false);

  const options = submissionOptions(view);
  const latest = latestChoice(view);
  const latestKey = choiceKey(latest);
  const resetKey = `${experimentId}\n${view.order.id}`;

  // An output card asked for an order: show that order's latest submission, once per request.
  if (request && request.kind === kind && request.nonce !== consumed) {
    setConsumed(request.nonce);
    const key = request.workOrderId === view.order.id ? null : latestOf(options, request.workOrderId);
    setPicked(key === null ? null : { resetKey, key });
  }

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

  // The lab's skill titles, once for every submission "Built from" shows.
  useEffect(() => {
    let live = true;
    client.listSkills(labId).then(
      (skills) => {
        if (!live) return;
        setSkillTitles(new Map(skills.map((s) => [s.id, s.title])));
        setSkillError(null);
      },
      (e: unknown) => {
        if (live) setSkillError(e instanceof ClientError ? e.message : "Couldn't load the lab's skills.");
      },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  const current = !isLatest && loaded && loaded.key === chosenKey ? loaded : null;
  const steps: S[] | null = isLatest ? view.steps : current && "steps" in current ? current.steps : null;
  const loadError = current && "error" in current ? current.error : null;

  if (shown && steps && (kept === null || kept.key !== chosenKey || kept.steps !== steps)) {
    setKept({ key: chosenKey, steps, results: shown.submission.results });
  }
  const onScreen: Kept<S> | null = shown && steps ? { key: chosenKey, steps, results: shown.submission.results } : kept;
  const loading = shown !== undefined && steps === null && loadError === null;

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
      <button type="button" className="ws-button hist-quiet" onClick={backToLatest} disabled={signing}>Back to the latest</button>
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
        headingRef={summary}
      >
        {options.length > 0 && (
          <>
            <span className="hist-row">
              <SubmissionPicker
                ref={picker}
                options={options}
                value={chosenKey}
                onChange={choose}
                pending={shown ? undefined : `${view.order.id}, nothing submitted yet`}
                disabled={signing}
              />
              <button
                ref={compareButton}
                type="button"
                className="ws-button hist-quiet hist-compare"
                aria-expanded={canCompare ? comparing : undefined}
                aria-controls={canCompare ? diffId : undefined}
                aria-describedby={canCompare ? undefined : hintId}
                disabled={!canCompare || signing}
                onClick={() => setComparing((open) => !open)}
              >
                Compare
              </button>
            </span>
            {/* Sign-off only ever names the latest submission of the newest order. */}
            {isLatest && shown && (
              <SignOff
                key={shown.key}
                order={shown.record.order}
                submission={shown.submission}
                onDone={() => summary.current?.focus()}
                onPendingChange={setSigning}
              />
            )}
          </>
        )}
      </SubmissionHeader>
      {comparing && canCompare && shown && (
        <SubmissionDiff key={shown.key} id={diffId} kind={kind} shown={shown} options={options} onClose={closeComparison} />
      )}
      {loadError && <p role="alert" className="pg-error hist-load-error">{loadError}</p>}
      <p role="status" className="hist-loading">
        {loading && shown ? `Loading ${shown.record.order.id} submission ${shown.submission.number}…` : ""}
      </p>
      {shown && onScreen && !loadError && (
        <div className="hist-steps" data-stale={loading ? "true" : "false"}>
          {renderSteps(onScreen.steps, unplacedFailures(onScreen.results, onScreen.steps))}
        </div>
      )}
      {shown && (
        <BuiltFrom
          order={shown.record.order}
          submission={shown.submission}
          history={shown.record.history}
          sources={steps ? citedSources(steps as { sources?: { id: string; title: string }[] }[]) : null}
          skillTitles={skillTitles}
          skillError={skillError}
        />
      )}
    </>
  );
}
