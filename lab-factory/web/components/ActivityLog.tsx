"use client";

import { Check, Dot, X } from "lucide-react";
import { useState } from "react";

import type { ActivityItem } from "../lib/types.ts";

const OUTCOME_TEXT: Record<ActivityItem["outcome"], string> = {
  done: "Done",
  passed: "Passed",
  failed: "Failed",
  info: "Note",
};

function OutcomeIcon({ outcome }: { outcome: ActivityItem["outcome"] }) {
  if (outcome === "failed") return <X size={16} aria-hidden="true" />;
  if (outcome === "info") return <Dot size={16} aria-hidden="true" />;
  return <Check size={16} aria-hidden="true" />;
}

export function stepCount(n: number): string {
  return n === 1 ? "1 step" : `${n} steps`;
}

/**
 * The factory's build steps as a collapsible list. `live` marks a log that is still streaming:
 * new lines fade in as they arrive. `open` sets whether it starts expanded; a streaming log and
 * one that has just finished start open, older logs start closed.
 */
export function ActivityLog({ items, live = false, open = false }: { items: ActivityItem[]; live?: boolean; open?: boolean }) {
  const [expanded, setExpanded] = useState(open || live);
  return (
    <details
      className={live ? "conv-activity conv-activity-live" : "conv-activity"}
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="conv-activity-summary">{stepCount(items.length)}</summary>
      <ul className="conv-activity-list" aria-label="Activity" aria-live="polite">
        {items.map((item) => (
          <li key={item.id} className={`conv-activity-item conv-outcome-${item.outcome}`}>
            <span className="conv-activity-icon"><OutcomeIcon outcome={item.outcome} /></span>
            <span className="visually-hidden">{OUTCOME_TEXT[item.outcome]}: </span>
            <span className="conv-activity-text">
              <span className="conv-activity-label">{item.label}</span>
              {item.detail ? <span className="conv-activity-detail">{item.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
