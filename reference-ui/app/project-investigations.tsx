"use client";

import { useState } from "react";
import { apiUrl } from "./research-api";
import { AppDetail, DraftDetail, Notice, useRead } from "./research-workflows";

export type Project = { id: string; title: string };
export type Resource = {
  id: string; title: string; kind: "app" | "procedure" | "data"; status?: string;
  path?: string; automatic?: boolean; tabular?: boolean; reused?: boolean; submission?: number;
};
export type Investigation = { id: string; project_id: string; objective: string; resources: Resource[] };
export type Question = { question: string; field: string; options: Project[]; matches?: Resource[] };
type Inventory = {
  context: { experiment: {goal: string; documents: {id:string; title:string; text:string}[]};
    lab: {name:string; documents: {id:string; title:string; text:string}[]; instruments:{id:string; name:string; model:string}[]};
    experiment_revision: number; lab_revision:number };
  resources: Resource[]; investigations: Investigation[] };
const kindLabel = { app: "Analysis app", procedure: "Procedure", data: "Dataset" };

function ResourceItem({ item, projectId }: { item: Resource; projectId: string }) {
  const [expanded, setExpanded] = useState(item.reused !== undefined && !item.path);
  const [draft, setDraft] = useState(item.id);
  const name = kindLabel[item.kind] + " · " + item.title;
  const portal = item.tabular || (item.kind === "procedure" && !item.automatic);
  return <div className="research-item">
    {item.path ? <a href={apiUrl(item.path)} download>{name}</a> : portal ?
      <a href={"#order/" + encodeURIComponent(item.id)}>{name}</a> :
      <button className="ws-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{name}</button>}
    <small>{item.id}{item.submission ? " · submission " + item.submission : ""}
      {item.reused === true ? " · reused" : item.reused === false ? " · requested" : ""}</small>
    {item.kind === "procedure" && item.status === "released" &&
      <a href={"#analysis/new?" + new URLSearchParams({project:projectId, procedure:item.id})}>Use this procedure for a tabular analysis</a>}
    {expanded && !portal && (item.kind === "app" ? <AppDetail id={item.id} /> : <DraftDetail key={draft} id={draft} open={setDraft} />)}
  </div>;
}

export function ProjectInvestigations({ projectId, active, open, compose }: {
  projectId: string; active?: string; open: (id: string) => void; compose: (objective: string) => void;
}) {
  const {data, error, refresh} = useRead<Inventory>("research-projects?project=" + encodeURIComponent(projectId));
  const current = data?.investigations.find(i => i.id === active);
  return <section className="research-workflows project-investigations">
    <div className="ws-sectionhead"><h2>Investigations</h2><button onClick={refresh}>Refresh</button></div>
    <Notice error={error} />
    {!data && !error && <p role="status">Loading project records…</p>}
    {data && <div className="ws-actions">
      <a className="ws-button" href={"#analysis/new?project=" + encodeURIComponent(projectId)}>Upload project readings</a>
      <details><summary>Registered lab context</summary><p>{data.context.experiment.goal}</p>
        <p>{data.context.lab.name} · lab revision {data.context.lab_revision} · experiment revision {data.context.experiment_revision}</p>
        {data.context.lab.instruments.map(i => <p key={i.id}>{i.name} · {i.model}</p>)}
        {[...data.context.lab.documents,...data.context.experiment.documents].map((d,i) =>
          <details key={i}><summary>{d.title}</summary><p>{d.text}</p></details>)}
        <div className="ws-actions"><a href="#context">Edit lab context</a>
          <button onClick={() => compose("Ask a worker to draft a procedure for " + data.context.experiment.goal)}>Request a worker draft</button></div>
      </details>
    </div>}
    {data?.investigations.length === 0 && <p>No investigations yet.</p>}
    {data?.investigations.map(i => <div key={i.id}>
      <button className="ws-button" aria-expanded={i.id === active} onClick={() => open(i.id === active ? "" : i.id)}>{i.objective}</button>
      {i.id === active && <div>{i.resources.map(item => <ResourceItem key={item.id} item={item} projectId={projectId} />)}</div>}
    </div>)}
    {active && data && !current && <p>That investigation is unavailable in this project.</p>}
    {!!data?.resources.length && <details><summary>Project data, procedures and apps ({data.resources.length})</summary>
      {data.resources.map(item => <ResourceItem key={item.id} item={item} projectId={projectId}/>)}</details>}
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
