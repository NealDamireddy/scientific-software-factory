"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Run, Snapshot, WorkspaceClient } from "./api";

function RecordedTime({ value }: { value: string | null }) {
  return value ? <time dateTime={value}>{value}</time> : <>Not recorded</>;
}

function Seconds({ value }: { value: number | null }) {
  return Number.isFinite(value) && value !== null ? (
    <>{value} s</>
  ) : (
    <>Not recorded</>
  );
}

function Metric({ value, empty }: { value: number | null; empty: string }) {
  return typeof value === "number" && Number.isFinite(value) ? (
    <>{value}</>
  ) : (
    <>{empty}</>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const experimentNames = {
  concentration: "Concentration",
  time_course: "Time course",
};
const provenanceNames = {
  simulated: "Simulated acquisition",
  archive: "Archived run",
  replay: "Replay of saved measurements",
};
const terminalIncomplete = new Set([
  "partial",
  "cancelled",
  "interrupted",
  "failed",
]);
const stages = [
  ["software", "Software preparation"],
  ["acquisition", "Acquisition"],
  ["analysis", "Analysis"],
] as const;

function RecordedProgress({ run }: { run: Run }) {
  return (
    <>
      <dl className="run-facts">
        <Fact label="Provenance">{provenanceNames[run.provenance]}</Fact>
        <Fact label="Run ID">
          <code>{run.run_id}</code>
        </Fact>
        <Fact label="Acquisition job ID">
          <code>{run.job_id ?? "Not assigned"}</code>
        </Fact>
        <Fact label="Submitted">
          <RecordedTime value={run.submitted_at} />
        </Fact>
        <Fact label="Specification digest">
          <code>{run.spec_digest}</code>
        </Fact>
        <Fact label="Approval">{run.approval}</Fact>
        <Fact label="Acquisition recipe">{run.recipe}</Fact>
      </dl>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Recorded stage timing"
      >
        <table className="run-stage-table">
          <caption>Recorded stages</caption>
          <thead>
            <tr>
              <th scope="col">Stage</th>
              <th scope="col">State</th>
              <th scope="col">Started</th>
              <th scope="col">Finished</th>
            </tr>
          </thead>
          <tbody>
            {stages.map(([stage, label]) => (
              <tr key={stage}>
                <th scope="row">{label}</th>
                <td>{run[stage]}</td>
                <td>
                  <RecordedTime value={run[`${stage}_started_at`]} />
                </td>
                <td>
                  <RecordedTime value={run[`${stage}_finished_at`]} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="run-facts">
        <Fact label="Software preparation decision">
          {run.preparation ?? "Not recorded"}
        </Fact>
        <Fact label="Verified release">
          <code>{run.release_id ?? "Not available"}</code>
        </Fact>
        <Fact label="Source revision">
          <code>{run.source_revision ?? "Not recorded"}</code>
        </Fact>
        <Fact label="Software-induced wait">
          <Seconds value={run.software_wait_s} />
          {run.software_wait_pending && " · pending at last update"}
        </Fact>
      </dl>
      {run.blockers.length > 0 && (
        <div className="run-notice">
          <h4>Recorded blockers</h4>
          <ul>
            {run.blockers.map((blocker, index) => (
              <li key={index}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function ScientificResult({ run }: { run: Run }) {
  if (run.acquisition !== "completed") {
    return (
      <p className="run-notice">
        {terminalIncomplete.has(run.acquisition)
          ? "Incomplete acquisition evidence. No completed scientific result is available."
          : "Acquisition is incomplete. Awaiting completed measurements."}
      </p>
    );
  }
  if (
    run.analysis !== "completed" ||
    !run.release_id ||
    !run.source_revision ||
    !run.result
  ) {
    return (
      <p className="run-notice">
        A verified scientific result is unavailable for this run.
      </p>
    );
  }
  const { calibration_id, unit, results } = run.result;
  const timeCourse = run.experiment_type === "time_course";
  return (
    <>
      <dl className="run-facts">
        <Fact label="Calibration">
          <code>{calibration_id}</code>
        </Fact>
        <Fact label="Concentration unit">{unit}</Fact>
      </dl>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Recorded scientific results"
      >
        <table className="run-results-table">
          <caption>
            {timeCourse
              ? "Recorded time-course measurements"
              : "Recorded concentration measurements"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Sample ID</th>
              {timeCourse && (
                <>
                  <th scope="col">Measured at</th>
                  <th scope="col">Elapsed from acquisition start</th>
                </>
              )}
              <th scope="col">Concentration ({unit})</th>
              <th scope="col">Replicate SD ({unit})</th>
              <th scope="col">Review reason</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row, index) => (
              <tr key={index}>
                <th scope="row">{row.sample_id}</th>
                {timeCourse && (
                  <>
                    <td>
                      <RecordedTime value={row.timestamp ?? null} />
                    </td>
                    <td>
                      <Seconds value={row.elapsed_s ?? null} />
                    </td>
                  </>
                )}
                <td>
                  <Metric value={row.concentration_mg_l} empty="Withheld" />
                </td>
                <td>
                  <Metric value={row.replicate_sd_mg_l} empty="Unavailable" />
                </td>
                <td>{row.review_reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type RunViewProps = {
  snapshot: Snapshot;
  client: WorkspaceClient;
  projectId: string;
  stale: boolean;
  operate: <T>(
    action: () => Promise<T>,
    refresh?: boolean,
  ) => Promise<T | undefined>;
};

function RunDetails({
  run,
  client,
  projectId,
  operate,
  stale,
  recordedAt,
}: Omit<RunViewProps, "snapshot"> & {
  run: Run;
  recordedAt: string;
}) {
  const mounted = useRef(false);
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function downloadEvidence() {
    setDownloading(true);
    try {
      const blob = await operate(
        () => client.evidence(projectId, run.run_id),
        false,
      );
      if (!mounted.current || !blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const extension = blob.type.includes("json")
        ? ".json"
        : blob.type.includes("zip")
          ? ".zip"
          : "";
      link.download = `evidence-${run.run_id.replace(/[^a-zA-Z0-9_-]/g, "_")}${extension}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      if (mounted.current) setDownloading(false);
    }
  }

  return (
    <section className="workspace-card" aria-label="Run details">
      <h2>{experimentNames[run.experiment_type]} run</h2>
      <p>
        {stale ? "Stale progress. Last known snapshot" : "Recorded snapshot"} ·{" "}
        <RecordedTime value={recordedAt} />
      </p>
      <RecordedProgress run={run} />
      <h3>Scientific result</h3>
      <ScientificResult run={run} />
      <p>
        <strong>Scientific review</strong> · {run.scientific_review}
      </p>
      <div className="actions">
        <button type="button" disabled={downloading} onClick={downloadEvidence}>
          {downloading ? "Requesting evidence…" : "Download evidence"}
        </button>
      </div>
    </section>
  );
}

export default function RunViews({ snapshot, ...props }: RunViewProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const heading = useId();
  const run =
    snapshot.runs.find((item) => item.run_id === selected) ?? snapshot.runs[0];
  if (!run)
    return (
      <section className="workspace-card">
        <h2>No experiment runs yet</h2>
        <p>
          Save lab and project context, then create and approve your first
          experiment specification to submit a run.
        </p>
      </section>
    );

  return (
    <>
      <section className="workspace-card" aria-labelledby={heading}>
        <h2 id={heading}>Experiment runs</h2>
        <div className="run-picker">
          {snapshot.runs.map((item) => (
            <button
              type="button"
              key={item.run_id}
              className="run-option"
              aria-pressed={item.run_id === run.run_id}
              onClick={() => setSelected(item.run_id)}
            >
              <strong>{experimentNames[item.experiment_type]}</strong>{" "}
              <code>{item.run_id}</code>
              <span>
                Acquisition {item.acquisition} · Analysis {item.analysis}
              </span>
            </button>
          ))}
        </div>
      </section>
      <RunDetails
        {...props}
        key={props.projectId + "/" + run.run_id}
        run={run}
        recordedAt={snapshot.recorded_at}
      />
    </>
  );
}
