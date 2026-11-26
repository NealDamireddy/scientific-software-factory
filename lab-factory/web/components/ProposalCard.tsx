"use client";

import { useRef, useState } from "react";

import type { OutputKind, Proposal } from "../lib/types.ts";
import { errorText, outputLabel } from "../lib/status.ts";

/**
 * The factory's plan: one checkbox per proposed output and `Build these`. While the build is running
 * it says `Building: …`, and once the factory's result has come back, `Built: …`; neither offers controls.
 */
export function ProposalCard({ proposal, built, busy, onBuild }: {
  proposal: Proposal;
  /** A later factory message carries the built outputs: the build is done. */
  built: boolean;
  /** Something else is in flight (a send or another build), so building waits. */
  busy: boolean;
  /** Starts the build. Rejects with the client's refusal. */
  onBuild: (outputs: OutputKind[]) => Promise<void>;
}) {
  const [chosen, setChosen] = useState<OutputKind[]>(proposal.outputs);
  const [building, setBuilding] = useState<OutputKind[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // State updates land after the click handler returns; a ref stops the second click of a double click.
  const inFlight = useRef(false);

  const accepted = proposal.accepted ?? building;
  if (accepted) {
    return (
      <p className="conv-proposal conv-proposal-done">
        {proposal.accepted && built ? "Built" : "Building"}: {accepted.map((kind) => outputLabel(kind)).join(", ")}
      </p>
    );
  }

  async function build() {
    if (inFlight.current || busy) return;
    const outputs = proposal.outputs.filter((kind) => chosen.includes(kind));
    if (outputs.length === 0) return;
    inFlight.current = true;
    setError(null);
    setBuilding(outputs);
    try {
      await onBuild(outputs);
    } catch (e) {
      setError(errorText(e));
    } finally {
      // By now the stored proposal carries `accepted` if the build happened.
      setBuilding(null);
      inFlight.current = false;
    }
  }

  function toggle(kind: OutputKind, on: boolean) {
    setChosen((current) => (on ? [...current, kind] : current.filter((k) => k !== kind)));
  }

  return (
    <fieldset className="conv-proposal">
      <legend className="visually-hidden">Outputs to build</legend>
      <ul className="conv-proposal-options">
        {proposal.outputs.map((kind) => (
          <li key={kind}>
            <label className="conv-proposal-option">
              <input type="checkbox" checked={chosen.includes(kind)} onChange={(e) => toggle(kind, e.currentTarget.checked)} />
              <span>{outputLabel(kind)}</span>
            </label>
          </li>
        ))}
      </ul>
      <button type="button" className="ws-button ws-button-primary" disabled={chosen.length === 0 || busy} onClick={build}>
        Build these
      </button>
      {error ? <p className="ws-error" role="alert">{error}</p> : null}
    </fieldset>
  );
}
