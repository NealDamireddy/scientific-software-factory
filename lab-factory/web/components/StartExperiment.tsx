"use client";

import "./pages.css";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { Instrument } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText } from "./pages-status.ts";

export function StartExperiment({ projectId }: { projectId?: string }) {
  const { client, labId, refresh, version } = useClient();
  const [, navigate] = useRoute();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [projects, setProjects] = useState<{ id: string; title: string }[]>([]);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [project, setProject] = useState("");
  const [description, setDescription] = useState("");
  const [loadedProjects, setLoadedProjects] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const projectsLoaded = projectId === undefined ? client.listProjects(labId) : Promise.resolve([]);
    Promise.all([client.getLab(labId), projectsLoaded]).then(
      ([lab, rows]) => {
        if (!live) return;
        setInstruments(lab.instruments);
        setLoadedProjects(true);
        setProjects(rows.map((p) => ({ id: p.id, title: p.title })));
        // The first instrument is checked by default, once; later refreshes keep the person's choice.
        setChosen((c) => c ?? lab.instruments.slice(0, 1).map((i) => i.id));
        setProject((p) => (rows.some((r) => r.id === p) ? p : rows[0]?.id ?? ""));
      },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, projectId, version]);

  const target = projectId ?? project;
  const noProject = projectId === undefined && loadedProjects && projects.length === 0;
  const noInstrument = (chosen ?? []).length === 0;

  function toggle(id: string, on: boolean) {
    setChosen((c) => {
      const current = c ?? [];
      return on ? [...current, id] : current.filter((x) => x !== id);
    });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending || target === "" || noInstrument) return;
    setPending(true);
    setError(null);
    try {
      const experiment = await client.createExperiment(target, description.trim(), chosen ?? []);
      refresh();
      navigate({ view: "experiment", projectId: experiment.project_id, experimentId: experiment.id });
    } catch (err) {
      setError(errorText(err));
      setPending(false);
    }
  }

  return (
    <form className="pg-form" onSubmit={onSubmit} aria-label="Start an experiment">
      <label className="pg-field">
        <span>Describe your experiment</span>
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      {instruments.length > 0 && (
        <fieldset className="pg-field pg-choices">
          <legend>Instruments</legend>
          {instruments.map((i) => (
            <label key={i.id} className="pg-choice">
              <input
                type="checkbox"
                checked={(chosen ?? []).includes(i.id)}
                onChange={(e) => toggle(i.id, e.target.checked)}
              />
              <span>{i.name}</span>
            </label>
          ))}
        </fieldset>
      )}
      {projectId === undefined && projects.length > 0 && (
        <label className="pg-field">
          <span>Project</span>
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </label>
      )}
      {noProject && <p className="pg-note">Create a project first.</p>}
      <div className="pg-actions">
        <button type="submit" className="pg-button" disabled={pending || description.trim() === "" || target === "" || noInstrument}>
          Start experiment
        </button>
        {noInstrument && loadedProjects && <span className="pg-note">Choose at least one instrument.</span>}
      </div>
      {error && <p role="alert" className="pg-error">{error}</p>}
    </form>
  );
}
