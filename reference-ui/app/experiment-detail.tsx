"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  FlaskConical,
  Folder,
  Pencil,
  Info,
  Layers,
  LineChart,
  List,
  Play,
  RotateCcw,
  Square,
  TriangleAlert,
} from "lucide-react";
import {
  cancel,
  prepareRunContext,
  pendingReview,
  simulationInstrument,
  repeatDilutionFactor,
  resultConcentration,
  sampleOriginal,
  sampleRepeat,
  type RunContext,
  type AgentCheck,
  editObjective,
  methodName,
  readings,
  requestChanges,
  resubmit,
  startRun,
  wavelength,
  type Experiment,
  type Run,
} from "./simulation";
import { buildAgentContext, type ExtensionState } from "./extension-model";
import "./experiment-detail.css";

type Props = {
  experiment: Experiment;
  extensions: ExtensionState;
  onChange: (experiment: Experiment) => void;
  onBack: () => void;
  instrumentBusy?: boolean;
};
type Tab = "Overview" | "Results" | "Evidence";
type Dialog = "changes" | "revision" | "approve" | "method" | "edit" | null;
const tabs: Tab[] = ["Overview", "Results", "Evidence"];
const stages = [
  "Prepare instrument",
  "Collect readings",
  "Check sample",
  "Verify result",
];
function statusTone(status: Experiment["status"]) {
  return status === "Verified"
    ? "good"
    : ["Awaiting approval", "Changes requested"].includes(status)
      ? "warn"
      : "";
}
function Chart({ experiment: e, run }: { experiment: Experiment; run: Run }) {
  const isB = e.kind === "b12";
  const points = readings(e, run);
  const [active, setActive] = useState<number | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const maxX = isB ? 10 : 120,
    maxY = isB ? 1.4 : 1;
  const px = (x: number) => 63 + (x / maxX) * 490,
    py = (y: number) => 212 - (y / maxY) * 179;
  const selected = active === null ? undefined : points[active];
  const flagged = run.outcome === "flagged";
  const hasSample = isB && (flagged || run.outcome === "verified");
  return (
    <section className="ex-chart">
      <div className="ex-card-head">
        <div>
          <h3>{isB ? "Calibration curve" : "Absorbance over time"}</h3>
          <p>UV–Vis absorbance at {wavelength(e.kind)} nm</p>
        </div>
        <div className="ex-segment" aria-label="Data presentation">
          <button
            aria-label="Show chart"
            aria-pressed={view === "chart"}
            onClick={() => setView("chart")}
          >
            <LineChart size={16} />
          </button>
          <button
            aria-label="Show data table"
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
          >
            <List size={16} />
          </button>
        </div>
      </div>
      {view === "chart" ? (
        <>
          <div className="ex-graph">
            <svg
              viewBox="0 0 600 259"
              role="group"
              aria-label={
                isB
                  ? "Standard concentration versus absorbance"
                  : "Time versus absorbance"
              }
            >
              <text x="61" y="17">
                Absorbance (AU)
              </text>
              {[0, 0.25, 0.5, 0.75, 1].map((f) => (
                <g key={f}>
                  <line
                    className="ex-grid"
                    x1="63"
                    x2="553"
                    y1={py(f * maxY)}
                    y2={py(f * maxY)}
                  />
                  <text x="49" y={py(f * maxY) + 4} textAnchor="end">
                    {(f * maxY).toFixed(2)}
                  </text>
                </g>
              ))}
              {(isB ? [0, 2, 4, 6, 8, 10] : [0, 30, 60, 90, 120]).map((x) => (
                <text key={x} x={px(x)} y="230" textAnchor="middle">
                  {x}
                </text>
              ))}
              <text x="308" y="251" textAnchor="middle">
                {isB ? "Standard concentration (µM)" : "Time (s)"}
              </text>
              <polyline
                className="ex-trace"
                points={points.map((p) => px(p.x) + "," + py(p.y)).join(" ")}
              />
              {hasSample && (
                <line
                  className={"ex-guide " + (flagged ? "ex-flag" : "")}
                  x1="63"
                  x2="553"
                  y1={py(flagged ? sampleOriginal : sampleRepeat)}
                  y2={py(flagged ? sampleOriginal : sampleRepeat)}
                />
              )}
              {points.map((p, i) => (
                <g
                  key={p.x}
                  tabIndex={0}
                  className="ex-point"
                  aria-label={
                    p.x +
                    (isB ? " micromolar, " : " seconds, ") +
                    p.y +
                    " absorbance units"
                  }
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                  onMouseEnter={() => setActive(i)}
                  onMouseLeave={() => setActive(null)}
                  onClick={() => setActive(i)}
                >
                  <circle
                    className="ex-target"
                    cx={px(p.x)}
                    cy={py(p.y)}
                    r="11"
                  />
                  <circle
                    cx={px(p.x)}
                    cy={py(p.y)}
                    r={active === i ? 5.5 : 3.7}
                  />
                </g>
              ))}
              {selected && (
                <g
                  className="ex-tooltip"
                  aria-hidden="true"
                  transform={
                    "translate(" +
                    Math.max(70, Math.min(479, px(selected.x) - 33)) +
                    "," +
                    (py(selected.y) - 34) +
                    ")"
                  }
                >
                  <rect width="73" height="24" rx="5" />
                  <text x="36.5" y="16" textAnchor="middle">
                    {selected.y.toFixed(3)} AU
                  </text>
                </g>
              )}
            </svg>
          </div>
          <div className="ex-legend">
            <span>
              <i />
              {isB ? "Calibration standards" : "Sample trace"}
            </span>
            {hasSample && (
              <span>
                <i className={"dashed " + (flagged ? "flag" : "")} />
                {flagged ? "Original" : "Repeat"} sample ·{" "}
                {(flagged ? sampleOriginal : sampleRepeat).toFixed(3)} AU
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="ex-table-wrap">
          <table>
            <thead>
              <tr>
                <th>{isB ? "Standard concentration (µM)" : "Time (s)"}</th>
                <th>Absorbance (AU)</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.x}>
                  <td>{p.x}</td>
                  <td>{p.y.toFixed(3)}</td>
                </tr>
              ))}
              {hasSample && (
                <tr>
                  <td>
                    {flagged ? "Original sample" : "Repeat sample"}{" "}
                    <span className="ex-muted">
                      · {flagged ? "undiluted" : "2× dilution"}
                    </span>
                  </td>
                  <td>
                    {(flagged ? sampleOriginal : sampleRepeat).toFixed(3)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ContextRecord({
  title,
  context,
  checks,
  run,
}: {
  title: string;
  context?: RunContext;
  checks?: AgentCheck[];
  run?: Run;
}) {
  if (!context)
    return (
      <div className="ex-context-legacy">
        <strong>{title}</strong>
        <p>Agent context wasn’t recorded for this run.</p>
      </div>
    );
  const { briefing, harness, skills, connectors } = context;
  return (
    <details className="ex-context">
      <summary>
        <span>
          <strong>{title}</strong>
          <small>
            {skills.length} {skills.length === 1 ? "skill" : "skills"} ·{" "}
            {connectors.length}{" "}
            {connectors.length === 1 ? "connector" : "connectors"}
          </small>
        </span>
        <ChevronRight size={16} />
      </summary>
      <div className="ex-context-content">
        <p>Local simulation · External services are never contacted.</p>
        <dl className="ex-context-facts">
          <dt>Objective</dt>
          <dd>{briefing.objective}</dd>
          <dt>Project</dt>
          <dd>{briefing.project}</dd>
          <dt>Method</dt>
          <dd>
            {briefing.method.name} v{briefing.method.revision} ·{" "}
            {briefing.method.wavelengthNm} nm
          </dd>
          <dt>Harness</dt>
          <dd>
            {harness ? (
              <>
                {harness.name}
                <code>{harness.endpoint}</code>
              </>
            ) : (
              "Workspace simulator"
            )}
          </dd>
        </dl>
        <h4>Skills</h4>
        {skills.length === 0 && <p>No enabled skills.</p>}
        {skills.map((skill) => {
          const check = checks?.find((c) => c.skillId === skill.id);
          const [label, detail] = run ? pendingReview(skill, run) : ["", ""];
          return (
            <div className="ex-context-entry" key={skill.id}>
              <strong>{skill.name}</strong>
              <p>
                <b>When to use</b> {skill.whenToUse}
              </p>
              <p>
                <b>Instructions</b> {skill.instructions}
              </p>
              {checks && (
                <p className="ex-application">
                  <b>
                    {check
                      ? {
                          clear: "Checked",
                          finding: "Finding",
                          unassessed: "Unassessed",
                        }[check.verdict ?? "clear"]
                      : label}
                  </b>{" "}
                  {check?.finding ?? detail}
                  {check?.stage && (
                    <span className="ex-check-stage">
                      {
                        {
                          start: "Run start",
                          result: "Result review",
                          repeat: "Repeat review",
                        }[check.stage]
                      }
                    </span>
                  )}
                  {check?.references?.length ? (
                    <span className="ex-check-refs">
                      <b>Evidence</b> {check.references.join(" · ")}
                    </span>
                  ) : null}
                </p>
              )}
            </div>
          );
        })}
        <h4>Connectors</h4>
        {connectors.length === 0 && <p>No selected connectors.</p>}
        {connectors.map((item) => (
          <div className="ex-context-entry" key={item.id}>
            <strong>{item.name}</strong>
            <p>{item.description}</p>
            {item.endpoint && <code>{item.endpoint}</code>}
          </div>
        ))}
      </div>
    </details>
  );
}

function Evidence({ e }: { e: Experiment }) {
  function download() {
    const record = {
      ...e,
      illustrative: true,
      method: {
        name: methodName(e.kind),
        version: "1.0",
        wavelengthNm: wavelength(e.kind),
        instrument: simulationInstrument,
      },
      runs: e.runs.map((run) => ({
        ...run,
        readings: readings(e, run),
        ...(e.kind === "b12" && ["verified", "flagged"].includes(run.outcome)
          ? {
              sampleAbsorbanceAU:
                run.mode === "original" ? sampleOriginal : sampleRepeat,
              dilutionFactor:
                run.mode === "original" ? 1 : repeatDilutionFactor,
            }
          : {}),
      })),
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = e.id + "-illustrative-evidence.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <div className="ex-section-head">
        <div>
          <h2>Evidence record</h2>
          <p>Inputs, decisions, and outputs for this experiment.</p>
        </div>
        <button className="ex-button" onClick={download}>
          <Download size={15} />
          Export JSON
        </button>
      </div>
      <div className="ex-specs">
        <div>
          <small>Source</small>
          <strong>Illustrative dataset</strong>
        </div>
        <div>
          <small>Method revision</small>
          <strong>Version 1.0</strong>
        </div>
        <div>
          <small>Recorded runs</small>
          <strong>{e.runs.length}</strong>
        </div>
      </div>
      {e.runs.length > 0 && (
        <section aria-label="Agent context by run">
          <h3 className="ex-subhead">Agent context by run</h3>
          {e.runs.map((r) => (
            <ContextRecord
              key={r.number}
              title={`Run ${r.number} · ${r.mode === "original" ? "Original sample" : "Diluted repeat"}`}
              run={r}
              context={r.agentContext}
              checks={r.agentChecks ?? []}
            />
          ))}
        </section>
      )}
      <h3 className="ex-subhead">Activity history</h3>
      <ol className="ex-timeline">
        {e.events.map((v, i) => (
          <li key={i}>
            <span className="ex-tick">
              <Check size={11} />
            </span>
            <div>
              <strong>{v.title}</strong>
              <p>{v.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}

export default function ExperimentDetail({
  experiment: e,
  extensions,
  onChange,
  onBack,
  instrumentBusy = false,
}: Props) {
  const [tab, setTab] = useState<Tab>("Overview"),
    [picked, setPicked] = useState<number | null>(null),
    [dialog, setDialog] = useState<Dialog>(null),
    [note, setNote] = useState("");
  const modal = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (dialog) modal.current?.showModal();
    else modal.current?.close();
  }, [dialog]);
  const run = e.runs.at(-1),
    shown = e.runs.find((r) => r.number === picked) ?? run;
  const isB = e.kind === "b12";
  const open = (v: Dialog) => {
    setNote(v === "edit" ? e.title : "");
    setDialog(v);
  };
  const execute = (repeat = false) => {
    if (instrumentBusy) return;
    setPicked(null);
    setTab("Overview");
    onChange(
      startRun(
        e,
        repeat ? "repeat" : "original",
        buildAgentContext(extensions),
      ),
    );
    setDialog(null);
  };
  return (
    <article className="ex-detail">
      <button className="ex-back" onClick={onBack}>
        <ArrowLeft size={16} />
        Back to workspace
      </button>
      <div className="ex-breadcrumb">
        <Folder size={15} />
        {e.project}
        <ChevronRight size={13} />
        Experiment
      </div>
      <div className="ex-title">
        <h1>{e.title}</h1>
        {e.status === "Draft" && (
          <button
            className="ex-icon"
            aria-label="Edit objective"
            onClick={() => open("edit")}
          >
            <Pencil size={15} />
          </button>
        )}
        <span className={"ex-status " + statusTone(e.status)}>
          <i />
          {e.status}
        </span>
      </div>
      <div className="ex-meta">
        <span>
          <FlaskConical size={15} />
          {simulationInstrument}
        </span>
        <span>
          <Layers size={15} />
          Illustrative data
        </span>
      </div>
      <nav className="ex-tabs" aria-label="Experiment views">
        {tabs.map((t) => (
          <button
            key={t}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>
      {instrumentBusy && (
        <p className="ex-busy" role="status">
          <Info size={15} />
          The UV–Vis spectrometer is in use by another simulation.
        </p>
      )}
      {tab === "Overview" && (
        <>
          {e.status === "Draft" && (
            <section className="ex-section-head">
              <div>
                <h2>Review experiment</h2>
                <p>
                  Starting the simulation automatically loads your enabled
                  skills and selected connectors.
                </p>
              </div>
              <button
                className="ex-primary"
                disabled={instrumentBusy}
                onClick={() => execute()}
              >
                <Play size={15} />
                Start simulation
              </button>
            </section>
          )}
          {e.status === "Draft" && (
            <ContextRecord
              title="Agent context for this run"
              context={prepareRunContext(
                e,
                "original",
                buildAgentContext(extensions),
              )}
            />
          )}
          {e.status === "Running" && run && (
            <section className="ex-run">
              <div className="ex-card-head">
                <div>
                  <div className="ex-kicker">
                    <Activity size={15} />
                    Run {run.number}
                  </div>
                  <h2>{stages[run.step]}</h2>
                </div>
                <button
                  className="ex-button"
                  onClick={() => onChange(cancel(e))}
                >
                  <Square size={13} />
                  Cancel run
                </button>
              </div>
              <div className="ex-progress">
                <i style={{ width: (run.step + 1) * 25 + "%" }} />
              </div>
              <p>
                Step {run.step + 1} of 4 · {readings(e, run).length} readings
                collected
              </p>
              {run.agentContext && (
                <p>
                  Agent context loaded · {run.agentContext.skills.length}{" "}
                  {run.agentContext.skills.length === 1 ? "skill" : "skills"} ·{" "}
                  {run.agentContext.connectors.length}{" "}
                  {run.agentContext.connectors.length === 1
                    ? "connector"
                    : "connectors"}
                </p>
              )}
            </section>
          )}
          {e.status === "Awaiting approval" && (
            <section className="ex-review">
              <div className="ex-kicker">
                <TriangleAlert size={16} />
                Scientific review
              </div>
              <h2>Sample exceeds calibration range</h2>
              <p>
                The original sample measured <strong>1.250 AU</strong>. The
                highest standard is <strong>0.850 AU</strong>. Concentration is
                withheld until a repeat falls within the measured range.
              </p>
              <div className="ex-actions">
                <button
                  className="ex-primary"
                  disabled={instrumentBusy}
                  onClick={() => open("approve")}
                >
                  <ClipboardCheck size={15} />
                  Review repeat
                </button>
                <button className="ex-button" onClick={() => open("changes")}>
                  Request changes
                </button>
              </div>
            </section>
          )}
          {e.status === "Changes requested" && (
            <section className="ex-review">
              <div className="ex-kicker">
                <FileText size={15} />
                Reviewer feedback
              </div>
              <h2>Revision requested</h2>
              <p>{e.events.at(-1)?.detail}</p>
              <button className="ex-primary" onClick={() => open("revision")}>
                Respond to reviewer
                <ArrowRight size={15} />
              </button>
            </section>
          )}
          {e.status === "Cancelled" && (
            <div className="ex-section-head">
              <div>
                <h2>Run cancelled</h2>
                <p>Your partial readings are saved in Results.</p>
              </div>
              <button
                className="ex-button"
                disabled={instrumentBusy}
                onClick={() => execute()}
              >
                <RotateCcw size={15} />
                Start a new run
              </button>
            </div>
          )}
          {e.status === "Verified" && (
            <section className="ex-section-head">
              <div>
                <div className="ex-kicker">
                  <CheckCircle2 size={15} />
                  Verified result
                </div>
                <h2>
                  {isB ? resultConcentration.toFixed(1) + " µM" : "0.367 AU"}
                </h2>
                <p>
                  {isB
                    ? "Original sample concentration, corrected for 2× dilution."
                    : "Final sample absorbance after 120 seconds."}
                </p>
              </div>
              <button className="ex-button" onClick={() => setTab("Results")}>
                View results
                <ArrowRight size={15} />
              </button>
            </section>
          )}
          <section className="ex-method">
            <div className="ex-card-head">
              <div>
                <div className="ex-kicker">
                  <BookOpen size={15} />
                  Experiment method
                </div>
                <h3>{methodName(e.kind)}</h3>
              </div>
              <button
                className="ex-icon"
                aria-label="Read method note"
                onClick={() => open("method")}
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <div className="ex-specs">
              <div>
                <small>Wavelength</small>
                <strong>{wavelength(e.kind)} nm</strong>
              </div>
              <div>
                <small>{isB ? "Standards" : "Duration"}</small>
                <strong>{isB ? "0–10 µM" : "120 seconds"}</strong>
              </div>
              <div>
                <small>Method revision</small>
                <strong>Version 1.0</strong>
              </div>
            </div>
          </section>
          {run && <Chart key={run.number} experiment={e} run={run} />}
        </>
      )}
      {tab === "Results" && (
        <>
          <div className="ex-section-head">
            <div>
              <h2>Experiment results</h2>
              <p>Inspect readings and compare individual runs.</p>
            </div>
            {e.runs.length > 0 && (
              <label className="ex-select">
                <select
                  aria-label="Select run"
                  value={shown?.number}
                  onChange={(ev) => setPicked(Number(ev.target.value))}
                >
                  {e.runs.map((r) => (
                    <option key={r.number} value={r.number}>
                      Run {r.number} ·{" "}
                      {r.mode === "repeat"
                        ? "Diluted repeat"
                        : "Original sample"}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {shown ? (
            <>
              {isB && shown.outcome === "verified" && (
                <section
                  className="ex-measurement"
                  aria-label="Verified concentration"
                >
                  <div className="ex-kicker">
                    <CheckCircle2 size={15} />
                    Verified concentration
                  </div>
                  <div className="ex-measurement-value">
                    <strong>{resultConcentration.toFixed(1)} µM</strong>
                    <span>Original sample · 2× dilution correction</span>
                  </div>
                </section>
              )}
              <Chart key={shown.number} experiment={e} run={shown} />
              <div className="ex-result-note">
                <Info size={17} />
                <div>
                  <strong>
                    {shown.outcome === "flagged"
                      ? "Concentration withheld"
                      : shown.outcome === "verified"
                        ? "Verified measurement"
                        : "Partial record"}
                  </strong>
                  <p>
                    {shown.outcome === "flagged"
                      ? "Original absorbance exceeded the 0.050–0.850 AU calibration range."
                      : shown.outcome === "verified"
                        ? isB
                          ? "The repeat measured 0.650 AU, equivalent to 7.5 µM. Applying the dilution factor gives 15.0 µM."
                          : "The original record contains nine measurements at 15-second intervals."
                        : "Only collected readings are shown for this run."}
                  </p>
                </div>
              </div>
              {e.status === "Verified" && (
                <button
                  className="ex-button"
                  disabled={instrumentBusy}
                  onClick={() => execute()}
                >
                  <RotateCcw size={14} />
                  Replay simulation
                </button>
              )}
            </>
          ) : (
            <div className="ex-empty">
              <LineChart />
              <h3>Results appear here</h3>
              <p>Start the simulation to collect your first readings.</p>
              <button className="ex-button" onClick={() => setTab("Overview")}>
                Review experiment
              </button>
            </div>
          )}
        </>
      )}
      {tab === "Evidence" && <Evidence e={e} />}
      <dialog
        ref={modal}
        className="ex-dialog"
        onCancel={() => setDialog(null)}
        onClick={(ev) => {
          if (ev.target === ev.currentTarget) setDialog(null);
        }}
        aria-labelledby="ex-dialog-title"
      >
        <div>
          <div className="ex-kicker">
            {dialog === "method" ? (
              <BookOpen size={16} />
            ) : (
              <ClipboardCheck size={16} />
            )}{" "}
            {dialog === "method"
              ? "Lab knowledge"
              : dialog === "edit"
                ? "Experiment draft"
                : "Scientific review"}
          </div>
          <h2 id="ex-dialog-title">
            {dialog === "method"
              ? methodName(e.kind)
              : dialog === "edit"
                ? "Edit objective"
                : dialog === "changes"
                  ? "Request changes"
                  : dialog === "revision"
                    ? "Respond to reviewer"
                    : "Approve a diluted repeat?"}
          </h2>
          {dialog === "method" ? (
            <>
              <p>
                {isB
                  ? "Compare the sample absorbance against six illustrative standards. Quantify only within the measured calibration range. For a diluted repeat, apply the dilution factor to the interpolated concentration."
                  : "Follow the illustrative sample trace for 120 seconds, recording absorbance every 15 seconds. Compare the final reading with the initial absorbance."}
              </p>
              <p className="ex-muted">Illustrative method · Revision 1.0</p>
            </>
          ) : dialog === "approve" ? (
            <p>
              Run a simulated measurement with a 2× dilution. The original
              reading and your approval will stay in the evidence record.
            </p>
          ) : (
            <label className="ex-field">
              {dialog === "edit"
                ? "Research objective"
                : dialog === "changes"
                  ? "What needs to change?"
                  : "Describe your revision"}
              <textarea
                autoFocus
                value={note}
                onChange={(ev) => setNote(ev.target.value)}
                placeholder={
                  dialog === "edit"
                    ? "Describe your research objective…"
                    : dialog === "changes"
                      ? "Add a note for the researcher…"
                      : "Add a note for the reviewer…"
                }
              />
            </label>
          )}
          <div className="ex-actions">
            <button className="ex-button" onClick={() => setDialog(null)}>
              {dialog === "method" ? "Close" : "Cancel"}
            </button>
            {dialog === "approve" && (
              <button
                className="ex-primary"
                disabled={instrumentBusy}
                onClick={() => execute(true)}
              >
                Approve and run
                <ArrowRight size={15} />
              </button>
            )}
            {(dialog === "changes" ||
              dialog === "revision" ||
              dialog === "edit") && (
              <button
                className="ex-primary"
                disabled={!note.trim()}
                onClick={() => {
                  onChange(
                    dialog === "edit"
                      ? editObjective(e, note)
                      : dialog === "changes"
                        ? requestChanges(e, note)
                        : resubmit(e, note),
                  );
                  setDialog(null);
                }}
              >
                {dialog === "edit"
                  ? "Save objective"
                  : dialog === "changes"
                    ? "Request changes"
                    : "Submit revision"}
              </button>
            )}
          </div>
        </div>
      </dialog>
    </article>
  );
}
