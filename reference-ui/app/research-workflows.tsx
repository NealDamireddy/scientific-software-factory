"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  apiUrl,
  researchRequest,
  type AnalysisApp,
  type Procedure,
  type RequestSummary,
} from "./research-api";
import "./research-workflows.css";

type Workflow = "analysis-apps" | "stage-plots" | "procedures";
const endpoints = {
  "analysis-apps": "analysis/apps",
  procedures: "procedure-drafts",
  "stage-plots": "analysis/drift",
};
const titles = { "stage-plots": "Stage drift plots", "analysis-apps": "Analysis apps", procedures: "Procedures" };
const label = (state: string) => state.replaceAll("_", " ");
const message = (failure: unknown) =>
  failure instanceof Error ? failure.message : "Lab Factory is unavailable.";

export function useRead<T>(path: string | undefined, pending?: (value:T) => boolean) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    setData(undefined);
    setError("");
    if (!path) return;
    const requestPath = path;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const value = await researchRequest<T>(requestPath, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setData(value);
        if (pending?.(value)) timer = setTimeout(read, 3000);
      } catch (failure) {
        if (!controller.signal.aborted) setError(message(failure));
      }
    }
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, version, pending]);
  return { data, error, refresh: () => setVersion((v) => v + 1) };
}

export function Notice({ error }: { error: string }) {
  return error ? (
    <p role="alert">
      {error}{" "}
      {error.includes("Sign in") && (
        <a href="#orders">
          Sign in to this workspace
        </a>
      )}
    </p>
  ) : null;
}

function Header({ title, refresh }: { title: string; refresh: () => void }) {
  return (
    <div className="ws-pagehead">
      <h1>{title}</h1>
      <button className="ws-button" onClick={refresh}>
        Refresh
      </button>
    </div>
  );
}

// Keep the request UUID on ambiguous failures. The actor and original payload determine server-side reuse.
function WriteForm({
  path,
  fields,
  children,
  submitLabel,
  onSaved,
  disabled = false,
  withId = true,
}: {
  path: string;
  fields: object;
  children?: ReactNode;
  submitLabel: string;
  disabled?: boolean;
  onSaved: (id: string) => void;
  withId?: boolean;
}) {
  const last = useRef({ fingerprint: "", id: "", storageKey: "" });
  const active = useRef(false);
  const mounted = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (active.current || disabled) return;
    active.current = true;
    setBusy(true);
    setError("");
    try {
      const fingerprint = JSON.stringify([path, fields]);
      // A tab reload may follow a lost response. Keep only the input digest and request UUID.
      if (withId && last.current.fingerprint !== fingerprint) {
        const digest = await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(fingerprint),
        );
        const storageKey =
          "labfactory.pending." +
          apiUrl(path) +
          "." +
          Array.from(new Uint8Array(digest), (byte) =>
            byte.toString(16).padStart(2, "0"),
          ).join("");
        let id: string = crypto.randomUUID();
        try {
          id = sessionStorage.getItem(storageKey) || id;
          sessionStorage.setItem(storageKey, id);
        } catch {
          /* In-memory retries still work if browser storage is unavailable. */
        }
        last.current = { fingerprint, id, storageKey };
      }
      const body = withId ? { ...fields, request_id: last.current.id } : fields;
      const result = await researchRequest<{
        id?: string;
        order?: { id: string };
      }>(path, body);
      const id = result.id || result.order?.id;
      if (!id) throw new Error("Lab Factory did not return a request ID.");
      if (withId) {
        try {
          sessionStorage.removeItem(last.current.storageKey);
        } catch {}
        last.current = { fingerprint: "", id: "", storageKey: "" };
      }
      if (mounted.current) onSaved(id);
    } catch (failure) {
      if (mounted.current) setError(message(failure));
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy || disabled}>
        {children}
        <button className="ws-button primary" type="submit">
          {busy ? "Saving…" : submitLabel}
        </button>
      </fieldset>
      <Notice error={error} />
    </form>
  );
}

function WorkerDrafts({ automatic }: {automatic: RequestSummary[]}) {
  const {data,error} = useRead<{orders:RequestSummary[]}>("procedures");
  const known = new Set(automatic.map(row => row.id));
  return <><Notice error={error}/>{data?.orders.filter(row => !known.has(row.id)).map(row =>
    <a className="ws-experiment-row" key={row.id} href={"#order/" + encodeURIComponent(row.id)}>
      <span className="ws-row-copy"><strong>{row.objective}</strong><small>{row.id}</small></span>
      <span className="ws-row-status">{label(row.status)}</span>
    </a>)}</>;
}

function Catalog({
  kind,
  open,
}: {
  kind: Workflow;
  open: (id: string) => void;
}) {
  const apps = kind !== "procedures";
  const [archiveObjective, setArchiveObjective] = useState("Plot stage drift from the archived acquisitions.");
  const requests = useRead<{
    requests?: RequestSummary[];
    drafts?: RequestSummary[];
  }>(endpoints[kind]);
  const rows = requests.data?.requests ?? requests.data?.drafts;
  return (
    <>
      <Header title={titles[kind]} refresh={requests.refresh} />
      <a href="#home">Start a project investigation</a>
      {kind === "procedures" && <WriteForm path="procedures" fields={{demo:true}} withId={false}
        submitLabel="Try the procedure review example" onSaved={id => { location.hash = "order/" + encodeURIComponent(id); }} />}
      {kind === "stage-plots" && <WriteForm path={endpoints[kind]}
        fields={{project:"stage-example", objective:archiveObjective.trim()}}
        submitLabel="Request a plot from the stage archive" onSaved={open}><label>Stage alignment example objective
        <textarea required maxLength={4000} value={archiveObjective} onChange={e=>setArchiveObjective(e.target.value)}/></label></WriteForm>}
      <h2>{apps ? "App requests" : "Procedure drafts"}</h2>
      <Notice error={requests.error} />
      {rows?.map((row) => (
        <button
          className="ws-experiment-row"
          key={row.id}
          onClick={() => open(row.id)}
        >
          <span className="ws-row-copy">
            <strong>{row.objective}</strong>
            <small>{row.id}</small>
          </span>
          <span className="ws-row-status">{label(row.status)}</span>
        </button>
      ))}
      {kind === "procedures" && rows && <WorkerDrafts automatic={rows}/>}
      {apps && rows?.length === 0 && (
        <p>No {apps ? "app requests" : "procedure drafts"} yet.</p>
      )}
      {!rows && !requests.error && <p role="status">Loading requests…</p>}
    </>
  );
}

function AttachToProject({id, refresh}: {id:string; refresh:()=>void}) {
  const {data,error} = useRead<{projects:{id:string; title:string}[]}>("research-projects");
  const [project,setProject] = useState("");
  return <><Notice error={error}/>{data?.projects.length ? <WriteForm path="research-projects"
    fields={{app_id:id,project_id:project}} withId={false} submitLabel="Add to project" onSaved={refresh}>
    <label>Research project<select required value={project} onChange={e=>setProject(e.target.value)}>
      <option value="">Choose a project</option>{data.projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}
    </select></label></WriteForm> : data ? <a href="#home">Create a project to save this analysis</a> : null}</>;
}

const waitingForAuthor = (app: AnalysisApp) => ["open", "in_progress"].includes(app.status);

export function AppDetail({ id, embedded = false }: { id: string; embedded?: boolean }) {
  const path = (id.startsWith("PLOT-") ? "analysis/drift" : endpoints["analysis-apps"]) + "/" + encodeURIComponent(id);
  const { data, error, refresh } = useRead<AnalysisApp>(path, waitingForAuthor);
  const [answer, setAnswer] = useState("");
  return (
    <>
      {!embedded && <Header title={data?.objective || "Analysis app"} refresh={refresh} />}
      <Notice error={error} />
      {data ? (
        <>
          {!embedded && <p>{data.id} · {label(data.status)}</p>}
          {!embedded && (data.project_id ? <a href={"#project/" + encodeURIComponent("lab:" + data.project_id)}>Open research project</a>
            : <AttachToProject id={data.id} refresh={refresh}/>)}
          {!embedded && data.contexts.map(({experiment, lab, stage_calibration}, i) => (
            <details key={i}><summary>{experiment.title} · revision {experiment.revision}</summary>
              <p>{lab.name} · lab revision {lab.revision}</p>
              {lab.instruments.map((record, n) => <p key={n}>{record.name} · {record.model} · firmware {record.firmware}</p>)}
              {stage_calibration && <p>Origin {stage_calibration.origin_mm} mm · {stage_calibration.reading_unit || "Export unit unconfirmed"}
                {stage_calibration.ticks_per_mm ? " · " + stage_calibration.ticks_per_mm + " ticks/mm" : ""}</p>}
            </details>
          ))}
          {data.status === "open" && <p>Queued for an analysis worker.</p>}
          {(embedded ? [...data.history].reverse() : data.history).map((item) => (
            <section key={item.turn}>
              {embedded ? <h3>{item.turn === data.history.at(-1)?.turn ? "Worker’s latest update" : "Earlier update"}</h3> : <h2>Turn {item.turn}</h2>}
              <p>{item.submission.summary}</p>
              {item.submission.question && <p>{item.submission.question}</p>}
              {item.answer && <p>Researcher reply · {item.answer}</p>}
            </section>
          ))}
          {data.status === "needs_input" && (
            <WriteForm
              key={data.turn}
              path={path + "/answers"}
              fields={{ turn: data.turn, answer: answer.trim() }}
              withId={false}
              submitLabel="Send answer"
              onSaved={() => {
                setAnswer("");
                refresh();
              }}
            >
              <label>
                Your answer
                <textarea
                  required
                  maxLength={6000}
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              </label>
            </WriteForm>
          )}
          <details><summary>Pinned project records</summary>
            {embedded && <p>{data.id} · {label(data.status)}{data.artifact_digest && " · SHA-256 " + data.artifact_digest}</p>}
            <pre>{JSON.stringify(data.contexts.map(({briefing, ...record}) => record), null, 2)}</pre>
          </details>
          {data.status === "ready" && id.startsWith("PLOT-") && <details><summary>Review the plotting recipe</summary>
            <pre>{JSON.stringify(data.history.at(-1)?.submission, null, 2)}</pre></details>}
          {!embedded && data.artifact_digest && <p>App SHA-256 · {data.artifact_digest}</p>}
          {data.status === "ready" && (
            <a className="ws-button" href={apiUrl(path + "/app")} download>
              Download analysis app
            </a>
          )}
        </>
      ) : (
        !error && <p role="status">Loading app request…</p>
      )}
    </>
  );
}

export function DraftDetail({ id, open, embedded = false }: { id: string; open: (id: string) => void; embedded?: boolean }) {
  const path = endpoints.procedures + "/" + encodeURIComponent(id);
  const { data, error, refresh } = useRead<Procedure>(path);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [method, setMethod] = useState("");
  const [sourceId, setSourceId] = useState("");
  return (
    <>
      {!embedded && <Header title={data?.order.objective || "Procedure draft"} refresh={refresh}/>}
      <Notice error={error} />
      {data ? (
        <>
          {embedded ? <details><summary>Procedure record</summary>
            <p>{data.order.id} · {label(data.state)} · {data.order.experiment_id} revision {data.order.experiment_revision}</p>
          </details> : <p>{data.order.id} · {label(data.state)} · {data.order.experiment_id} revision {data.order.experiment_revision}</p>}
          {embedded && data.state === "needs_input" && <p>This procedure needs input before the worker can finish the draft.</p>}
          {data.previous_order && (
            <button
              className="ws-button"
              onClick={() => open(data.previous_order!)}
            >
              Previous draft · {data.previous_order}
            </button>
          )}
          {data.next_order && (
            <button
              className="ws-button"
              onClick={() => open(data.next_order!)}
            >
              Updated draft · {data.next_order}
            </button>
          )}
          {data.question && (
            <p>
              <strong>
                {data.question_step ? `Step ${data.question_step} · ` : ""}
                {data.question}
              </strong>
            </p>
          )}
          {data.submission?.artifact.steps && (
            <>
              <h2>Submission {data.submission.number}</h2>
              <ol>
                {data.submission.artifact.steps.map((step, i) => (
                  <li key={i}>
                    {step.text}
                    {step.action && (
                      <p>
                        {step.action.instrument_id} · {step.action.command}{" "}
                        {step.action.settings
                          .map((s) => `${s.parameter} ${s.value} ${s.unit}`)
                          .join(", ")}
                      </p>
                    )}
                    {step.amounts?.map((a, n) => (
                      <p key={n}>
                        {a.what} · {a.value} {a.unit}
                      </p>
                    ))}
                    {step.citations?.length ? (
                      <small>Sources · {step.citations.join(", ")}</small>
                    ) : null}
                  </li>
                ))}
              </ol>
            </>
          )}
          {data.sources.length > 0 && (
            <details>
              <summary>Source passages</summary>
              {data.sources.map((s, index) => (
                <blockquote key={index}>
                  <strong>
                    {s.title} · {s.document}, passage {s.passage}
                  </strong>
                  <p>{s.text}</p>
                </blockquote>
              ))}
            </details>
          )}
          {data.state === "needs_input" && (
            <WriteForm
              path={path + "/answers"}
              fields={
                method
                  ? { method_id: method }
                  : { title: title.trim(), text: text.trim(), ...(sourceId && { source_id: sourceId }) }
              }
              submitLabel="Save answer and redraft"
              onSaved={open}
            >
              {data.documents.length > 0 && (
                <label>
                  Answer with
                  <select
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                  >
                    <option value="">A new source or decision</option>
                    {data.documents.map((doc, i) => (
                      <option key={i} value={doc.id}>
                        {doc.title} · {doc.id}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!method && (
                <>
                  <label>
                    Source or decision title
                    <input
                      required
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </label>
                  {!!data.suggested_sources?.length && (
                    <label>
                      This text comes from
                      <select
                        value={sourceId}
                        onChange={(e) => setSourceId(e.target.value)}
                      >
                        <option value="">Another source</option>
                        {data.suggested_sources.map((src) => (
                          <option key={src.id} value={src.id}>
                            {src.title} · {src.locator}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    Method passage or decision
                    <textarea
                      required
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                    />
                  </label>
                </>
              )}
            </WriteForm>
          )}
          {data.state === "in_review" && (
            <a href={"#order/" + encodeURIComponent(id)}>
              Review submission
            </a>
          )}
        </>
      ) : (
        !error && <p role="status">Loading procedure draft…</p>
      )}
    </>
  );
}

export default function ResearchWorkflows({
  kind,
  id,
  go,
}: {
  kind: Workflow;
  id: string;
  go: (route: string) => void;
}) {
  const open = (next: string) => go(kind + "/" + encodeURIComponent(next));
  return (
    <section className="ws-page research-workflows">
      {id && (
        <button className="ws-button" onClick={() => go(kind)}>
          Back to {titles[kind].toLowerCase()}
        </button>
      )}
      {!id ? (
        <Catalog kind={kind} open={open} />
      ) : kind !== "procedures" ? (
        <AppDetail id={id} />
      ) : (
        <DraftDetail id={id} open={open} />
      )}
    </section>
  );
}
