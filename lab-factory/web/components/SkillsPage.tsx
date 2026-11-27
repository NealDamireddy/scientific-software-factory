"use client";

import "./pages.css";
import "./extensions.css";

import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { Skill } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText } from "./pages-status.ts";
import { SkillEditor } from "./SkillEditor.tsx";

type Notice = { skill: Skill; text: string };

export function SkillsPage({ skill }: { skill?: string }) {
  const { client, labId, version, refresh } = useClient();
  const [, navigate] = useRoute();
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [busy, setBusy] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    let live = true;
    client.listSkills(labId).then(
      (rows) => { if (live) { setSkills(rows); setError(null); } },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  // A save message belongs to one skill: opening another one clears it.
  useEffect(() => {
    setNotice((n) => (n && n.skill.id !== skill ? null : n));
  }, [skill]);

  async function toggle(s: Skill) {
    if (busy.includes(s.id)) return;
    setBusy((b) => [...b, s.id]);
    setError(null);
    try {
      const updated = await client.setSkillEnabled(labId, s.id, !s.enabled);
      setSkills((rows) => rows && rows.map((r) => (r.id === updated.id ? updated : r)));
      refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy((b) => b.filter((id) => id !== s.id));
    }
  }

  const isNew = skill === "new";
  const found = skill === undefined || isNew
    ? null
    : skills?.find((s) => s.id === skill) ?? (notice && notice.skill.id === skill ? notice.skill : null);

  return (
    <div className="page pg-page ext-page">
      <div className="ext-head">
        <div>
          <h1>Skills</h1>
          <p className="ext-intro">Instructions every agent follows when it works for this lab.</p>
          <p className="ext-note">Skills that are switched on are followed every time the factory builds.</p>
        </div>
        <a className="pg-button ext-link" href={routeHref({ view: "skills", skill: "new" })}>New skill</a>
      </div>

      {error && <p role="alert" className="pg-error ext-error">{error}</p>}
      {!skills && !error && <p className="pg-note">Loading</p>}
      {skills && (
        <ul className="pg-list" aria-label="Skills">
          {skills.map((s) => (
            <li key={s.id} className="ext-skill">
              <span className="ext-skill-text">
                <span className="ext-skill-title">{s.title}</span>
                <span className="ext-skill-description">{s.description}</span>
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={s.enabled}
                aria-label={`${s.title} enabled`}
                className="ext-switch"
                disabled={busy.includes(s.id)}
                onClick={() => toggle(s)}
              >
                <span className="ext-switch-track" aria-hidden="true"><span className="ext-switch-thumb" /></span>
                <span className="ext-switch-state" aria-hidden="true">{s.enabled ? "On" : "Off"}</span>
              </button>
              <a className="ext-quiet-link" href={routeHref({ view: "skills", skill: s.id })} aria-label={`Edit ${s.title}`}>
                Edit
              </a>
            </li>
          ))}
        </ul>
      )}

      {skill !== undefined && (isNew || skills) && (
        <section className="ext-editor" aria-labelledby="ext-editor-heading">
          <div className="ext-head">
            <h2 id="ext-editor-heading">{found || isNew ? (isNew ? "New skill" : "Edit skill") : "Skill"}</h2>
            <a className="ext-quiet-link" href={routeHref({ view: "skills" })}>Close</a>
          </div>
          {!isNew && !found && <p className="pg-note">That skill doesn&apos;t exist in this lab.</p>}
          {(isNew || found) && (
            <SkillEditor
              key={isNew ? "new" : skill}
              skill={found}
              notice={notice && notice.skill.id === (found?.id ?? "") ? notice.text : null}
              onEdited={() => setNotice(null)}
              onSaved={(saved, text) => {
                setNotice({ skill: saved, text });
                if (isNew) navigate({ view: "skills", skill: saved.id });
              }}
            />
          )}
        </section>
      )}
    </div>
  );
}
