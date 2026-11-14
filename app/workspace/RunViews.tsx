"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Timeline } from "./Timeline";
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
  simulated: "Simulated instrument",
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

function runState(run: Run) {
  if (terminalIncomplete.has(run.acquisition)) return "Acquisition " + run.acquisition;
  if (run.analysis === "completed" && run.acquisition === "completed") return "Complete";
  if (run.acquisition === "completed" || run.analysis === "blocked") return "Analysis " + run.analysis;
  return "Acquisition " + run.acquisition;
}

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
  demo: boolean;
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
  demo,
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

  const result = run.acquisition === "completed" && run.analysis === "completed" &&
    run.release_id && run.source_revision ? run.result : null;
  const rows = result?.results ?? [];
  const single = run.experiment_type === "concentration" && rows.length === 1;
  const reasons = [...new Set(rows.flatMap(row => row.review_reason ? [row.review_reason] : []))];
  const coursePoint = run.experiment_type === "time_course"
    ? rows.find(row => row.concentration_mg_l !== null && row.elapsed_s != null)
    : undefined;
  return (
    <section className="workspace-card selected-run" aria-label="Run details">
      <p className="run-origin">{demo ? "Recorded demo run" : "Workspace run"} · {provenanceNames[run.provenance]}</p>
      <div className="run-title"><h1>{experimentNames[run.experiment_type]} run</h1><strong>{runState(run)}</strong></div>
      <p className="release">{run.preparation === "reuse" ? "Reused software release" : "Software release"} <b>{run.release_id ?? "Awaiting verified release"}</b></p>
      <div className="run-overview">
        <Timeline run={run}/>
        <section className="outcome">
          <h3>{result ? "Scientific result" : "Run status"}</h3>
          {result ? <>
            <p>{single ? rows[0].sample_id : experimentNames[run.experiment_type]}</p>
            <strong className="reading">{single ? (rows[0].concentration_mg_l === null ? "Withheld" : rows[0].concentration_mg_l + " " + result.unit) :
              rows.length + (run.experiment_type === "time_course" ? " time points" : " measurements")}</strong>
            {single && <p>Replicate SD {rows[0].replicate_sd_mg_l === null ? "unavailable" : rows[0].replicate_sd_mg_l + " " + result.unit}</p>}
            {coursePoint && <p>{coursePoint.concentration_mg_l} {result.unit} at {coursePoint.elapsed_s} s</p>}
            {reasons.map(reason => <p key={reason}>{reason}</p>)}
          </> : <ScientificResult run={run}/>}
          {run.blockers.map((blocker,i) => <p key={i}>{blocker}</p>)}
          <p className="review"><strong>Scientific review</strong>{run.scientific_review}</p>
        </section>
      </div>
      {result && <ScientificResult run={run}/>}
      <details className="technical"><summary>Run details and exact timestamps</summary>
        <p>{stale ? "Stale progress. Last known snapshot" : "Recorded snapshot"} · <RecordedTime value={recordedAt}/></p>
        <RecordedProgress run={run}/>
      </details>
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
    <div className="runs-layout">
      <section className="run-index" aria-labelledby={heading}>
        <h2 id={heading}>Experiment runs</h2>
        <div className="run-picker">
          {snapshot.runs.map((item) => (
            <button
              type="button"
              key={item.run_id}
              className="run-option"
              data-run-id={item.run_id}
              aria-pressed={item.run_id === run.run_id}
              onClick={() => setSelected(item.run_id)}
            >
              <strong>{experimentNames[item.experiment_type]} · {runState(item)}</strong>
              <span>
                {item.result?.results[0]?.sample_id || snapshot.specifications.find(s => s.sha256 === item.spec_digest)?.sample_ids.join(", ") || "Sample unspecified"} · {item.submitted_at.split("T")[1]?.replace("Z", " UTC") || item.submitted_at}
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
    </div>
  );
}
