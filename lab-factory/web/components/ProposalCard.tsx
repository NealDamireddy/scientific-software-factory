"use client";

import { useRef, useState } from "react";

import type { OutputKind, Proposal } from "../lib/types.ts";
import { OUTPUT_LABEL } from "./OutputPanel.tsx";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The factory's plan: one checkbox per proposed output and `Build these`. Once accepted (or while
 * the build is running) it states what is being built and offers no controls.
 */
export function ProposalCard({ proposal, busy, onBuild }: {
  proposal: Proposal;
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
        Building: {accepted.map((kind) => OUTPUT_LABEL[kind]).join(", ")}
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
              <span>{OUTPUT_LABEL[kind]}</span>
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
