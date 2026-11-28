"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { BookOpen, ChartColumn, ChevronRight, ClipboardList, FileSpreadsheet, Files, FlaskConical, Pencil, Plus, RefreshCw, Upload } from "lucide-react";
import type { Procedure } from "./research-api";
import { apiUrl, researchRequest } from "./research-api";
import { AppDetail, DraftDetail, Notice, useRead } from "./research-workflows";
import { formatBytes, scopeLabel, shareable, type LibraryEntry } from "./library-model";

export type Project = { id: string; title: string; lab_id?: string; lab_name?: string; hypothesis?: string };
export type Resource = {
  id: string; title: string; kind: "app" | "procedure" | "data"; status?: string;
  path?: string; automatic?: boolean; tabular?: boolean; reused?: boolean; submission?: number;
  briefing?: {
    skills: {id: string; name: string; version: string}[];
    references: {id: string; kind: string; title: string; url: string; locator: string; document_id?: string}[];
    instrument: string | null;
  };
  library?: {document_id: string; source_id: string; title: string; scope: "shared" | "lab"; entry_id: number; revision: number}[];
};
export type Investigation = { id: string; project_id: string; experiment_id?: string; objective: string; resources: Resource[] };
export type Question = { question: string; field: string; options: Project[]; matches?: Resource[] };
export type ResearchExperimentSummary = { id: string; project_id: string; title: string; question: string; finding: string };
type Experiment = ResearchExperimentSummary & {requests: Investigation[]; resources: Resource[]};
type Inventory = {
  hypothesis: string; experiments: Experiment[];
  context: { experiment: {goal: string; documents: {id:string; title:string; text:string}[]};
    lab: {id:string; name:string; documents: {id:string; title:string; text:string}[]; instruments:{id:string; name:string; model:string}[]};
    experiment_revision: number; lab_revision:number };
  resources: Resource[]; investigations: Investigation[] };
const kindLabel = { app: "Analysis app", procedure: "Procedure", data: "Dataset" };

type OrderDetail = {
  order: {status: string; worker?: string};
  draft?: {next_order?: string};
  submissions: {
    number: number;
    artifact: NonNullable<Procedure["submission"]>["artifact"] & {needs_input?: string};
    rendered: string;
    source_passages?: Procedure["sources"];
  }[];
};

function awaitingDraft(order: OrderDetail) {
  return !order.submissions.length && ["open", "in_progress"].includes(order.order.status);
}

function WorkerProcedure({id}: {id: string}) {
  const {data, error} = useRead<OrderDetail>("orders/" + encodeURIComponent(id) + "?submission=latest", awaitingDraft);
  const submission = data?.submissions[0];
  return <section className="project-worker-draft" aria-label="Worker procedure draft">
    <Notice error={error}/>
    {!data && !error && <p role="status">Loading procedure…</p>}
    {data && <>
      <div className="project-draft-heading"><h3>Procedure draft</h3>
        <span>{data.order.status.replaceAll("_", " ")}{submission && " · submission " + submission.number}</span></div>
      {!submission && <p role="status">{data.order.worker ? data.order.worker + " is preparing the draft." : "Queued for a procedure worker."}</p>}
      {submission?.artifact.needs_input && <p>{submission.artifact.needs_input}</p>}
      {submission?.artifact.steps?.length ? <ol className="project-procedure-steps">
        {submission.artifact.steps.map((step, index) => <li key={index}>
          {step.text}
          {step.action && <p>{step.action.instrument_id} · {step.action.command}
            {step.action.settings.map(s => " · " + s.parameter + " " + s.value + " " + s.unit).join("")}</p>}
          {step.amounts?.map((a,i) => <p key={i}>{a.what} · {a.value} {a.unit}</p>)}
          {!!step.citations?.length && <small>Sources · {step.citations.join(", ")}</small>}
        </li>)}
      </ol> : submission && !submission.artifact.needs_input && <pre>{submission.rendered}</pre>}
      {!!submission?.source_passages?.length && <details>
        <summary>Source passages</summary>
        {submission.source_passages.map(p => <blockquote key={p.document + "/" + p.passage}>
          <strong>{p.title} · passage {p.passage}</strong><p>{p.text}</p>
        </blockquote>)}
      </details>}
      {data.draft?.next_order && <a href={"#order/" + encodeURIComponent(data.draft.next_order)}>Open updated draft</a>}
    </>}
    <a className="ws-button" href={"#order/" + encodeURIComponent(id)}>{submission ? "Review submission" : "Open work order"}</a>
  </section>;
}

const resourceIcon = {app: ChartColumn, procedure: ClipboardList, data: FileSpreadsheet};

function ResourceItem({item, projectId, showByDefault = false, objective, experimentId, usedIn, open}: {
  item: Resource; projectId: string; showByDefault?: boolean; objective?: string; experimentId?: string;
  usedIn?: ResearchExperimentSummary[]; open: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(showByDefault);
  const [draft, setDraft] = useState(item.id);
  const name = item.title === objective && !item.tabular && item.kind !== "data" ? kindLabel[item.kind] : item.title;
  const Icon = resourceIcon[item.kind];
  const label = <><Icon size={18} aria-hidden/><span>{name}</span></>;
  return <div className="project-resource">
    <div className="project-resource-head">
      {item.path ? <a className="project-resource-title" href={apiUrl(item.path)} download>{label}</a> :
        item.tabular ? <a className="project-resource-title" href={"#order/" + encodeURIComponent(item.id)}>{label}</a> :
        <button className="project-resource-title" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {label}<ChevronRight className="project-chevron" size={16} aria-hidden/>
        </button>}
      <small>{kindLabel[item.kind]}{item.status && " · " + workStatus(item.status)}{item.submission ? " · submission " + item.submission : ""}
        {item.reused === true ? " · reused" : item.reused === false ? " · requested" : ""}</small>
    </div>
    {!!usedIn?.length && <div className="project-used-in"><span>Used in</span>{usedIn.map(e =>
      <button key={e.id} onClick={() => open(e.id)}>{e.title}</button>)}</div>}
    {expanded && !item.path && !item.tabular && <div className="project-resource-view">{item.kind === "app"
      ? <AppDetail id={item.id} embedded/> : item.automatic
      ? <DraftDetail key={draft} id={draft} open={setDraft} embedded/> : <WorkerProcedure id={item.id}/>}</div>}
    {item.kind === "procedure" && item.status === "released" &&
      <a href={"#analysis/new?" + new URLSearchParams({project:projectId, procedure:item.id, ...(experimentId && {experiment:experimentId})})}>Use this procedure for a tabular analysis</a>}
    {(item.briefing || item.library?.length) && <details className="project-briefing">
      <summary>Agent briefing</summary>
      {!!item.briefing?.skills.length && <p>Skills · {item.briefing.skills.map((s, n) =>
        <span key={s.id}>{n > 0 && ", "}<span title={s.version}>{s.name}</span></span>)}</p>}
      {item.briefing?.instrument && <p>Instrument · {item.briefing.instrument}</p>}
      {!!item.library?.length && <>
        <h4>Pinned library text</h4>
        <ul>{item.library.map(l => <li key={l.document_id}>{l.title} · {scopeLabel(l.scope)}</li>)}</ul>
      </>}
      {!!item.briefing?.references.length && <>
        <h4>Suggested sources</h4>
        <ul>{item.briefing.references.map(r => <li key={r.id}>
          <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a> · {r.locator}{r.document_id && " · pinned as text"}</li>)}</ul>
      </>}
      {(!!item.briefing?.references.length || !!item.library?.length) &&
        <p className="project-briefing-note">Pinned library text can be cited. Other suggested sources are pointers until their text is added to the library.</p>}
    </details>}
  </div>;
}

function workStatus(status: string) {
  const labels: Record<string, string> = {
    open: "Queued", in_progress: "In progress", in_review: "Ready for review", ready: "Ready to use",
    released: "Released", needs_input: "Needs your input", drafting: "Drafting", failed: "Failed",
  };
  return labels[status] || status.replaceAll("_", " ");
}

function experimentStatus(experiment: Experiment) {
  // Show the state of the most recent request when the researcher has yet to record a finding.
  const request = experiment.requests[0];
  const newest = request?.resources.find(item => item.reused === false) || request?.resources[0];
  const item = experiment.resources.find(resource => resource.id === newest?.id) || experiment.resources[0];
  if (!item) return request ? "Your work has been requested." : "You can add data or request work.";
  if (item.kind === "data") return "The dataset is attached.";
  const subject = item.kind === "procedure" ? "Your procedure" : "Your analysis app";
  switch (item.status) {
    case "open": return subject + " is waiting for a worker.";
    case "drafting":
    case "in_progress": return item.kind === "procedure" ? "A worker is drafting your procedure." : "A worker is building your analysis app.";
    case "in_review": return subject + (item.kind === "procedure" ? " draft" : "") + " is ready for review.";
    case "released":
    case "ready": return subject + " is ready to use.";
    case "needs_input": return subject + " needs your input.";
    case "failed": return "The worker could not complete your " + (item.kind === "procedure" ? "procedure." : "analysis app.");
    default: return subject + " is attached.";
  }
}

type SaveMetadata = (fields: Record<string, string>) => Promise<void>;
type EditableSection = "hypothesis" | "finding" | "experiment";

function RecordEditor({section, initial, cancel, save}: {
  section: EditableSection; initial: Record<string,string>; cancel: () => void; save: SaveMetadata;
}) {
  const [values, setValues] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = section === "experiment" ? ["title", "question"] : [section];
  const labels: Record<string,string> = {title: "Experiment title", question: "Research question", finding: "Finding", hypothesis: "Project hypothesis"};
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await save(Object.fromEntries(fields.map(key => [key, values[key].trim()])));
      cancel();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save your changes.");
    } finally {
      setBusy(false);
    }
  }
  return <form className="project-editor" onSubmit={submit}>
    {fields.map((key, index) => <label key={key}>{labels[key]}
      {key === "title"
        ? <input autoFocus={index === 0} maxLength={120} required value={values[key]} disabled={busy}
            onChange={e => setValues({...values,[key]:e.target.value})}/>
        : <textarea autoFocus={index === 0} rows={3} maxLength={4000} required={key === "question"} value={values[key]} disabled={busy}
            onChange={e => setValues({...values,[key]:e.target.value})}/>}
    </label>)}
    <Notice error={error}/>
    <div className="project-editor-actions"><button className="ws-button primary" disabled={busy || (section === "experiment" && (!values.title.trim() || !values.question.trim()))}>Save {section}</button>
      <button type="button" className="ws-button" disabled={busy} onClick={cancel}>Cancel</button></div>
  </form>;
}

export function RecordNote({section, value, save}: {section: "finding" | "hypothesis"; value: string; save: SaveMetadata}) {
  const [editing, setEditing] = useState(false);
  const heading = section === "hypothesis" ? "Hypothesis" : "Finding";
  return <section className="project-record-section">
    <div className="ws-sectionhead"><h2>{heading}</h2>
      {!editing && <button onClick={() => setEditing(true)} aria-label={"Edit " + section}><Pencil size={16} aria-hidden/>Edit {section}</button>}</div>
    {editing ? <RecordEditor section={section} initial={{[section]:value}} save={save} cancel={() => setEditing(false)}/>
      : <p className={value ? "project-note" : "project-note empty"}>{value || (section === "hypothesis" ? "No hypothesis recorded yet." : "No finding recorded yet.")}</p>}
  </section>;
}

type RecordProps = {
  projectId: string; active?: string; open: (id: string) => void; compose: (objective: string) => void;
  simulatedExperiments?: ReactNode; onAddWork: (experimentId: string) => void; onChange: () => void;
};

function AttachFromProject({items, save}: {items: Resource[]; save: SaveMetadata}) {
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function attach(event: FormEvent) {
    event.preventDefault();
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      await save({attach_resource_id: selected});
      setSelected("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not attach project work.");
    } finally {
      setBusy(false);
    }
  }
  if (!items.length) return null;
  return <details className="project-disclosure project-reuse"><summary><Files size={17} aria-hidden/>Use existing project work<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
    <form className="project-attach-form" onSubmit={attach}>
      <label>Project resource<select value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
        <option value="">Select data, a procedure or an app</option>
        {items.map(r => <option key={r.id} value={r.id}>{kindLabel[r.kind]} · {r.title}</option>)}
      </select></label>
      <button className="ws-button" disabled={!selected || busy}>Attach to experiment</button><Notice error={error}/>
    </form>
  </details>;
}

function LabLibrary({labId}: {labId: string}) {
  const {data, error, refresh} = useRead<{entries: LibraryEntry[]}>("library?lab_id=" + encodeURIComponent(labId));
  const [failure, setFailure] = useState("");
  async function share(entry: LibraryEntry) {
    if (!window.confirm("Share “" + entry.title + "” with every lab? This cannot be undone.")) return;
    setFailure("");
    try {
      await researchRequest("library/" + entry.id + "/share", {});
      refresh();
    } catch (problem) {
      setFailure(problem instanceof Error ? problem.message : "Sharing failed.");
    }
  }
  return <section className="project-lab-library" aria-label="Lab library">
    <h3>Lab library</h3>
    <Notice error={error || failure}/>
    {data && (data.entries.length === 0
      ? <p className="project-note empty">No source text yet. Text you supply when a worker asks for a source is kept here for this lab.</p>
      : <ul>{data.entries.map(e => <li key={e.id}>
        <strong>{e.title}</strong>
        <small>{scopeLabel(e.scope)} · {formatBytes(e.bytes)} · {e.contributed_by} · revision {e.revision}</small>
        {shareable(e, data.entries) && <button className="ws-button" onClick={() => share(e)}>Share with all labs</button>}
      </li>)}</ul>)}
  </section>;
}

function ExperimentRecord({experiment, inventory, open, onAddWork, save}: {
  experiment: Experiment; inventory: Inventory; open: RecordProps["open"]; onAddWork: RecordProps["onAddWork"]; save: SaveMetadata;
}) {
  const [editing, setEditing] = useState(false);
  const request = experiment.requests[0];
  const expandedWork = request?.resources.filter(r => r.reused === false);
  const defaultWork = expandedWork?.length ? expandedWork : request?.resources;
  const uploadQuery = new URLSearchParams({project: experiment.project_id, experiment: experiment.id});
  // The project listing carries current records only; the agent briefing lives on the request that created the work.
  const created = new Map(experiment.requests.flatMap(r => r.resources).filter(r => r.briefing || r.library).map(r => [r.id, {briefing: r.briefing, library: r.library}]));
  return <>
    <header className="ws-pagehead project-experiment-head">
      <div><div className="ws-eyebrow">Experiment</div><h1>{experiment.title}</h1></div>
      <div className="project-editor-actions">
        {!editing && <button className="ws-button" onClick={() => setEditing(true)}><Pencil size={16} aria-hidden/>Edit experiment</button>}
        <button className="ws-button primary" onClick={() => onAddWork(experiment.id)}><Plus size={16} aria-hidden/>Add work</button>
      </div>
    </header>
    {editing ? <RecordEditor section="experiment" initial={{title:experiment.title, question:experiment.question}} save={save} cancel={() => setEditing(false)}/>
      : <div className="project-question"><h2>Research question</h2><p>{experiment.question}</p></div>}
    <RecordNote section="finding" value={experiment.finding} save={save}/>
    <section className="project-record-section">
      <div className="ws-sectionhead"><h2>Attached work</h2><a className="ws-button" href={"#analysis/new?" + uploadQuery}><Upload size={16} aria-hidden/>Upload readings</a></div>
      <div className="project-attached-work">{experiment.resources.map(item => <ResourceItem key={item.id}
        item={created.has(item.id) ? {...item, ...created.get(item.id)} : item}
        projectId={experiment.project_id} experimentId={experiment.id} open={open}
        objective={experiment.question}
        usedIn={inventory.experiments.filter(e => e.id !== experiment.id && e.resources.some(r => r.id === item.id))}
        showByDefault={defaultWork?.some(r => r.id === item.id)}/>)}</div>
      {experiment.resources.length === 0 && <p className="project-note empty">No data, procedures or apps attached yet.</p>}
      <AttachFromProject items={inventory.resources.filter(r => !experiment.resources.some(item => item.id === r.id))} save={save}/>
    </section>
    <details className="project-disclosure project-request-history"><summary>Request history ({experiment.requests.length})<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
      {experiment.requests.length ? <ol>{experiment.requests.map(r => <li key={r.id}>
        <p>{r.objective}</p>
        {r.resources.map(item => <small key={item.id}>{kindLabel[item.kind]} · {item.reused ? "Reused" : "Requested"} · {item.title === r.objective ? item.id : item.title}</small>)}
      </li>)}</ol> : <p className="project-note empty">No requests yet.</p>}
    </details>
  </>;
}

export function ProjectInvestigations({ projectId, active, open, compose, onAddWork, onChange, simulatedExperiments }: RecordProps) {
  const {data, error, refresh} = useRead<Inventory>("research-projects?project=" + encodeURIComponent(projectId));
  async function save(fields: Record<string,string>) {
    const endpoint = active ? "research-experiments/" + encodeURIComponent(active) : "research-projects";
    await researchRequest(endpoint, {project_id:projectId, ...fields});
    refresh();
    onChange();
  }
  const experiment = data?.experiments.find(e => e.id === active);
  return <section className="research-workflows project-investigations">
    <Notice error={error}/>
    {!data && !error && <p role="status">Loading project records…</p>}
    {data && (active ? (experiment ?
      <ExperimentRecord key={experiment.id} experiment={experiment} inventory={data} open={open} onAddWork={onAddWork} save={save}/> :
      <p>That experiment is unavailable in this project.</p>) : <>
      <RecordNote section="hypothesis" value={data.hypothesis} save={save}/>
      <section className="project-record-section">
        <div className="ws-sectionhead"><h2>Experiments</h2><button onClick={refresh}><RefreshCw size={16} aria-hidden/>Refresh</button></div>
        {data.experiments.length === 0 && !simulatedExperiments && <p className="project-note empty">No experiments yet.</p>}
        <div className="project-investigation-list">{data.experiments.map(e => <article key={e.id} className="project-investigation">
          <button className="ws-experiment-row" aria-label={e.title} onClick={() => open(e.id)}>
            <span className="project-investigation-icon"><FlaskConical size={23} aria-hidden/></span>
            <span className="ws-row-copy"><strong>{e.title}</strong>
              {e.question !== e.title && !e.requests.some(r => r.objective === e.question) && <small className="project-row-question">{e.question}</small>}
              <small className="project-row-outcome">{e.finding ? "Finding · " + e.finding : experimentStatus(e)}</small></span>
            <ChevronRight className="project-chevron" size={19} aria-hidden/>
          </button>
        </article>)}{simulatedExperiments}</div>
      </section>
      <div className="ws-sectionhead project-materials-heading"><h2>Project resources</h2>
        <a className="ws-button" href={"#analysis/new?project=" + encodeURIComponent(projectId)}><Upload size={16} aria-hidden/>Upload project readings</a></div>
      <details className="project-disclosure"><summary><Files size={19} aria-hidden/>Data, procedures and apps ({data.resources.length})<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
        {data.resources.length === 0 ? <p>No saved resources yet.</p> : data.resources.map(item => <ResourceItem key={item.id} item={item} projectId={projectId} open={open}
          usedIn={data.experiments.filter(e => e.resources.some(r => r.id === item.id))}/>)}
      </details>
      <details className="project-disclosure"><summary><BookOpen size={19} aria-hidden/>Registered lab context<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
        <div className="project-context">
          <p>{data.context.experiment.goal}</p>
          <p>{data.context.lab.name} · lab revision {data.context.lab_revision} · experiment revision {data.context.experiment_revision}</p>
          {data.context.lab.instruments.map(i => <p key={i.id}>{i.name} · {i.model}</p>)}
          {[...data.context.lab.documents,...data.context.experiment.documents].map((d,i) =>
            <details key={i}><summary>{d.title}</summary><p>{d.text}</p></details>)}
          <LabLibrary labId={data.context.lab.id}/>
          <div className="project-context-actions"><a href="#context">Edit lab context</a>
            <button className="ws-button" onClick={() => compose("Ask a worker to draft a procedure for " + data.context.experiment.goal)}>Request a worker draft</button></div>
        </div>
      </details>
    </>)}
  </section>;
}

type LibraryRecord = { id: string; owner: string; owner_id: string; revision: number;
  name?: string; model?: string; firmware?: string; title?: string; text?: string; source?: string; kind?: string;
  commands?: { name: string }[] };

export function RegisteredLibrary({ kind, query }: {kind: "documents" | "instruments"; query: string}) {
  const {data, error} = useRead<{records: LibraryRecord[]}>("research-projects?resources=" + kind);
  const matches = data?.records.filter(r => [r.title,r.name,r.model,r.owner,r.id,r.source,r.text]
    .some(value => value?.toLowerCase().includes(query.trim().toLowerCase())));
  return <section className="project-investigations"><h2>Registered {kind}</h2><Notice error={error}/>
    {matches?.map((r,i) => <details key={r.owner_id + "/" + r.id + i}><summary>{r.name || r.title} · {r.owner}</summary>
      <p>{r.owner_id} · revision {r.revision} · {r.id}</p>
      {r.model && <p>{r.model} · firmware {r.firmware}</p>}
      {r.commands?.map(c => <p key={c.name}>{c.name}</p>)}
      {r.source && <p>{r.source}</p>}{r.text && <p>{r.text}</p>}
    </details>)}
    {matches?.length === 0 && <p>No matching registered {kind}.</p>}
  </section>;
}


export type AnalysisSources = {experiment_id:string; experiment_revision:number; lab_revision:number;
  lab_document_ids:string[]; experiment_document_ids:string[]};

export function ProjectSources({id, value, set}: {id:string; value?:AnalysisSources; set:(s?:AnalysisSources)=>void}) {
  const {data, error} = useRead<Inventory>("research-projects?project=" + encodeURIComponent(id));
  if (!data) return <Notice error={error}/>;
  const context = data.context;
  const selected = value || {experiment_id:id, experiment_revision:context.experiment_revision,
    lab_revision:context.lab_revision, lab_document_ids:[], experiment_document_ids:context.experiment.documents.map(d=>d.id)};
  return <fieldset><legend>Documents for a new analysis app</legend>
    {(["lab", "experiment"] as const).map(scope => context[scope].documents.map(d => {
      const field = scope === "lab" ? "lab_document_ids" : "experiment_document_ids";
      return <label key={scope+d.id}><input type="checkbox" checked={selected[field].includes(d.id)}
        onChange={e => set({...selected,[field]:e.target.checked ? [...selected[field],d.id] : selected[field].filter(id=>id!==d.id)})}/>
        {d.title} · {scope}</label>;
    }))}
    {!context.lab.documents.length && !context.experiment.documents.length && <p>No documents registered in this project.</p>}
    {value && <button type="button" onClick={()=>set(undefined)}>Use project defaults</button>}
  </fieldset>;
}
