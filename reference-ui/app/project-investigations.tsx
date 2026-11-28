"use client";

import { useState } from "react";
import { BookOpen, ChartColumn, ChevronRight, ClipboardList, FileSpreadsheet, Files, FlaskConical, RefreshCw, Upload } from "lucide-react";
import type { Procedure } from "./research-api";
import { apiUrl } from "./research-api";
import { AppDetail, DraftDetail, Notice, useRead } from "./research-workflows";

export type Project = { id: string; title: string };
export type Resource = {
  id: string; title: string; kind: "app" | "procedure" | "data"; status?: string;
  path?: string; automatic?: boolean; tabular?: boolean; reused?: boolean; submission?: number;
  briefing?: {
    skills: {id: string; name: string; version: string}[];
    references: {id: string; kind: string; title: string; url: string; locator: string}[];
    instrument: string | null;
  };
};
export type Investigation = { id: string; project_id: string; objective: string; resources: Resource[] };
export type Question = { question: string; field: string; options: Project[]; matches?: Resource[] };
type Inventory = {
  context: { experiment: {goal: string; documents: {id:string; title:string; text:string}[]};
    lab: {name:string; documents: {id:string; title:string; text:string}[]; instruments:{id:string; name:string; model:string}[]};
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

function ResourceItem({item, projectId, showByDefault = false, objective}: {
  item: Resource; projectId: string; showByDefault?: boolean; objective?: string;
}) {
  const [expanded, setExpanded] = useState(showByDefault);
  const [draft, setDraft] = useState(item.id);
  const name = kindLabel[item.kind] + " · " + item.title;
  const Icon = resourceIcon[item.kind];
  const label = <><Icon size={18} aria-hidden/><span>{item.title === objective && !item.tabular ? kindLabel[item.kind] : name}</span></>;
  return <div className="project-resource">
    <div className="project-resource-head">
      {item.path ? <a className="project-resource-title" href={apiUrl(item.path)} download>{label}</a> :
        item.tabular ? <a className="project-resource-title" href={"#order/" + encodeURIComponent(item.id)}>{label}</a> :
        <button className="project-resource-title" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {label}<ChevronRight className="project-chevron" size={16} aria-hidden/>
        </button>}
      <small>{item.id}{item.submission ? " · submission " + item.submission : ""}
        {item.reused === true ? " · reused" : item.reused === false ? " · requested" : ""}</small>
    </div>
    {expanded && !item.path && !item.tabular && <div className="project-resource-view">{item.kind === "app"
      ? <AppDetail id={item.id}/> : item.automatic
      ? <DraftDetail key={draft} id={draft} open={setDraft}/> : <WorkerProcedure id={item.id}/>}</div>}
    {item.kind === "procedure" && item.status === "released" &&
      <a href={"#analysis/new?" + new URLSearchParams({project:projectId, procedure:item.id})}>Use this procedure for a tabular analysis</a>}
    {item.briefing && <details className="project-briefing">
      <summary>Agent briefing</summary>
      {item.briefing.skills.length > 0 && <p>Skills · {item.briefing.skills.map((s, n) =>
        <span key={s.id}>{n > 0 && ", "}<span title={s.version}>{s.name}</span></span>)}</p>}
      {item.briefing.instrument && <p>Instrument · {item.briefing.instrument}</p>}
      {item.briefing.references.length > 0 && <>
        <h4>Suggested sources</h4>
        <ul>{item.briefing.references.map(r => <li key={r.id}>
          <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a> · {r.locator}</li>)}</ul>
      </>}
      <p className="project-briefing-note">Suggested sources are pointers from the reference library. A worker cannot cite them until their text is added to the project.</p>
    </details>}
  </div>;
}

export function ProjectInvestigations({ projectId, active, open, compose }: {
  projectId: string; active?: string; open: (id: string) => void; compose: (objective: string) => void;
}) {
  const {data, error, refresh} = useRead<Inventory>("research-projects?project=" + encodeURIComponent(projectId));
  return <section className="research-workflows project-investigations">
    <div className="ws-sectionhead"><h2>Investigations</h2><button onClick={refresh}><RefreshCw size={16} aria-hidden/>Refresh</button></div>
    <Notice error={error}/>
    {!data && !error && <p role="status">Loading project records…</p>}
    {data && <>
      {data.investigations.length === 0 && <p>No investigations yet.</p>}
      <div className="project-investigation-list">{data.investigations.map(i => {
        const kinds = [...new Set(i.resources.map(r => kindLabel[r.kind]))];
        const expanded = i.id === active;
        const hasNewResource = i.resources.some(r => r.reused === false);
        return <article key={i.id} className="project-investigation">
          <button className="ws-experiment-row" aria-expanded={expanded} onClick={() => open(expanded ? "" : i.id)}>
            <span className="project-investigation-icon"><FlaskConical size={23} aria-hidden/></span>
            <span className="ws-row-copy"><strong>{i.objective}</strong>{kinds.length > 0 && <small>{kinds.join(" · ")}</small>}</span>
            <ChevronRight className="project-chevron" size={19} aria-hidden/>
          </button>
          {expanded && <div className="project-investigation-output">
            {i.resources.map(item => <ResourceItem key={item.id} item={item} projectId={projectId}
              objective={i.objective} showByDefault={item.reused === false || !hasNewResource}/>)}
          </div>}
        </article>;
      })}</div>
      {active && !data.investigations.some(i => i.id === active) && <p>That investigation is unavailable in this project.</p>}
      <div className="ws-sectionhead project-materials-heading"><h2>Project resources</h2>
        <a className="ws-button" href={"#analysis/new?project=" + encodeURIComponent(projectId)}><Upload size={16} aria-hidden/>Upload project readings</a></div>
      <details className="project-disclosure"><summary><Files size={19} aria-hidden/>Data, procedures and apps ({data.resources.length})<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
        {data.resources.length === 0 ? <p>No saved resources yet.</p> : data.resources.map(item => <ResourceItem key={item.id} item={item} projectId={projectId}/>)}
      </details>
      <details className="project-disclosure"><summary><BookOpen size={19} aria-hidden/>Registered lab context<ChevronRight className="project-chevron" size={16} aria-hidden/></summary>
        <div className="project-context">
          <p>{data.context.experiment.goal}</p>
          <p>{data.context.lab.name} · lab revision {data.context.lab_revision} · experiment revision {data.context.experiment_revision}</p>
          {data.context.lab.instruments.map(i => <p key={i.id}>{i.name} · {i.model}</p>)}
          {[...data.context.lab.documents,...data.context.experiment.documents].map((d,i) =>
            <details key={i}><summary>{d.title}</summary><p>{d.text}</p></details>)}
          <div className="project-context-actions"><a href="#context">Edit lab context</a>
            <button className="ws-button" onClick={() => compose("Ask a worker to draft a procedure for " + data.context.experiment.goal)}>Request a worker draft</button></div>
        </div>
      </details>
    </>}
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
