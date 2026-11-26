"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import { canConfirm, nameChoices, signOffMessage } from "../lib/signoff.ts";
import type { SignOffKind } from "../lib/signoff.ts";
import type { LabSettings, Submission, WorkOrder } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";

export type SignOffProps = {
  order: WorkOrder;
  /** The submission on show. Mount this only while it is the latest of the newest order. */
  submission: Submission;
  /** Called once a sign-off goes through, to move focus to the submission summary. */
  onDone?: () => void;
};

/**
 * Approve or reject the shown submission by number, for approvers, while the order waits for sign-off.
 * Each button reveals its own inline form; only one is open at a time. The client applies the lab's
 * sign-off rule and refuses a stale submission; a refusal shows in the form, which stays open.
 * Mount it keyed by the order and submission, so a new submission starts with closed forms.
 */
export function SignOff({ order, submission, onDone }: SignOffProps) {
  const { client, labId, role, version, refresh } = useClient();
  const uid = useId();
  const [open, setOpen] = useState<SignOffKind | null>(null);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  // Keyed by attempt, so the same refusal twice is a new alert and is announced again.
  const [error, setError] = useState<{ message: string; attempt: number } | null>(null);
  const attempts = useRef(0);
  const [done, setDone] = useState(false);
  const [settings, setSettings] = useState<LabSettings | null>(null);
  // Set before the request starts, so a second click in the same moment finds it taken.
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const approveButton = useRef<HTMLButtonElement>(null);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const firstField = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const focusField = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  // The lab's rule decides whether the name is typed or chosen from a list.
  useEffect(() => {
    let live = true;
    client.getSettings(labId).then(
      (s) => { if (live) setSettings(s); },
      // Without the rule the name is typed; the client still applies the rule and says so.
      () => { if (live) setSettings(null); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  useEffect(() => {
    if (!focusField.current) return;
    focusField.current = false;
    firstField.current?.focus();
  }, [open]);

  if (role !== "approver" || order.status !== "in_review" || done) return null;

  const n = submission.number;
  const choices = nameChoices(settings);
  // A name typed under one rule is dropped if the listed rule doesn't offer it.
  const nameValue = choices && !choices.includes(name) ? "" : name;
  const ready = open !== null && canConfirm(open, { name: nameValue, reason }) && !pending;
  const formId = `${uid}-form`;

  function reveal(kind: SignOffKind) {
    if (inFlight.current) return;
    setError(null);
    focusField.current = open !== kind;
    setOpen((current) => (current === kind ? null : kind));
  }

  function cancel() {
    if (inFlight.current) return;
    const button = open === "reject" ? rejectButton.current : approveButton.current;
    setOpen(null);
    setError(null);
    button?.focus();
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const kind = open;
    if (kind === null || inFlight.current || !canConfirm(kind, { name: nameValue, reason })) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      if (kind === "approve") await client.approve(order.id, n, nameValue);
      else await client.reject(order.id, n, nameValue, reason);
      if (!mounted.current) return;
      setDone(true);
      setOpen(null);
      refresh();
      onDone?.();
    } catch (e) {
      if (mounted.current) setError({ message: signOffMessage(e), attempt: ++attempts.current });
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  }

  return (
    <>
      <span className="signoff-buttons">
        <button
          ref={approveButton}
          type="button"
          className="ws-button ws-button-primary signoff-approve"
          aria-expanded={open === "approve"}
          aria-controls={open === "approve" ? formId : undefined}
          onClick={() => reveal("approve")}
        >
          Approve submission {n}
        </button>
        <button
          ref={rejectButton}
          type="button"
          className="ws-button hist-quiet signoff-reject"
          aria-expanded={open === "reject"}
          aria-controls={open === "reject" ? formId : undefined}
          onClick={() => reveal("reject")}
        >
          Reject submission {n}
        </button>
      </span>
      {open !== null && (
        <form
          id={formId}
          className="signoff-form"
          aria-label={`${open === "approve" ? "Approve" : "Reject"} submission ${n}`}
          onSubmit={confirm}
          onKeyDown={onKeyDown}
        >
          {choices ? (
            <label className="pg-field signoff-field">
              <span>Your name</span>
              <select ref={firstField} value={nameValue} onChange={(e) => setName(e.target.value)} disabled={pending}>
                <option value="" disabled>Choose your name</option>
                {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
              </select>
            </label>
          ) : (
            <label className="pg-field signoff-field">
              <span>Your name</span>
              <input
                ref={firstField}
                type="text"
                autoComplete="name"
                value={nameValue}
                onChange={(e) => setName(e.target.value)}
                readOnly={pending}
              />
            </label>
          )}
          {open === "reject" && (
            <label className="pg-field signoff-field">
              <span>Reason</span>
              <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} readOnly={pending} />
            </label>
          )}
          {error && <p key={error.attempt} role="alert" className="pg-error signoff-error">{error.message}</p>}
          <div className="signoff-form-actions">
            <button type="submit" className="ws-button ws-button-primary" disabled={!ready}>
              {open === "approve" ? "Approve" : "Reject"}
            </button>
            <button type="button" className="ws-button hist-quiet" onClick={cancel} disabled={pending}>Cancel</button>
          </div>
        </form>
      )}
    </>
  );
}
