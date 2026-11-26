"use client";

import { CircleX } from "lucide-react";
import { Fragment } from "react";

import { routeHref } from "../lib/route.ts";
import type { CheckResult, SettingView, StepView } from "../lib/types.ts";
import { useRoute } from "./ClientContext.tsx";
import { sentenceCase } from "./pages-status.ts";
import { RangeStrip } from "./RangeStrip.tsx";

export const PROCEDURE_LINE =
  "Only settings shown on a range are checked against your instruments. The rest is written for you and your approver to judge.";

/** Checked settings: one range strip each, straight from the factory's view. Nothing is recomputed. */
export function SettingStrips({ settings }: { settings: SettingView[] }) {
  if (settings.length === 0) return null;
  return (
    <div className="proc-settings">
      {settings.map((s, i) => (
        <RangeStrip
          key={`${s.parameter}-${i}`}
          parameter={s.parameter}
          label={sentenceCase(s.parameter)}
          display={s.display}
          canonical={s.canonical}
        />
      ))}
    </div>
  );
}

/** The factory's failing checks for a step, each with its detail. The UI shows them; it never decides them. */
export function StepFailures({ failures }: { failures: CheckResult[] }) {
  if (failures.length === 0) return null;
  return (
    <div className="proc-failures">
      {failures.map((f, i) => (
        <div key={`${f.name}-${i}`} role="note" className="proc-fail">
          <CircleX className="proc-fail-icon" size={16} aria-hidden="true" />
          <span>{f.name}: {f.detail}</span>
        </div>
      ))}
    </div>
  );
}

/** Failing checks of the shown submission that belong to no rendered step, so none passes silently. */
export function UnplacedFailures({ failures }: { failures: CheckResult[] }) {
  if (failures.length === 0) return null;
  return (
    <div className="proc-unplaced">
      <p className="proc-unplaced-head">Checks that failed outside the steps</p>
      <StepFailures failures={failures} />
    </div>
  );
}

export type ProcedureViewProps = {
  /** The steps of the shown submission, which may be an earlier one the person picked. */
  steps: StepView[];
  /** Failing checks no step carries (see `unplacedFailures`), listed above the steps. */
  unplaced?: CheckResult[];
};

/**
 * A procedure as one continuous numbered list. Settings sit on range strips (checked), amounts and
 * notes carry the sand label (not checked), and failing checks sit on their step (failed).
 */
export function ProcedureView({ steps, unplaced = [] }: ProcedureViewProps) {
  const [route] = useRoute();
  return (
    <div className="proc">
      <p className="proc-scope">{PROCEDURE_LINE}</p>
      <UnplacedFailures failures={unplaced} />
      <ol className="proc-steps" role="list" aria-label="Steps">
        {steps.map((step) => (
          <li key={step.number} className="proc-step">
            <span className="proc-num">{step.number}</span>
            <div className="proc-body">
              <p className="proc-text">
                {step.text}
                {/* Real spaces before and between the sources keep them apart from the words and from
                    each other; the sources wrap as one unit after the text. */}
                {step.sources.length > 0 && " "}
                {step.sources.length > 0 && (
                  <span className="proc-sources">
                    {step.sources.map((source, i) => (
                      <Fragment key={source.id}>
                        {i > 0 && " "}
                        <a className="proc-source" href={routeHref({ ...route, doc: source.id })}>{source.title}</a>
                      </Fragment>
                    ))}
                  </span>
                )}
              </p>
              <SettingStrips settings={step.settings} />
              {step.unchecked.length > 0 && (
                <div className="proc-unchecked-list">
                  {step.unchecked.map((entry, i) => (
                    <span key={`${entry}-${i}`} className="proc-unchecked">Not checked: {entry}</span>
                  ))}
                </div>
              )}
              <StepFailures failures={step.failures} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
