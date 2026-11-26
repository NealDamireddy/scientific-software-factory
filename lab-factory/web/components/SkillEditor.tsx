"use client";

import "./pages.css";
import "./extensions.css";

import { useState } from "react";
import type { FormEvent } from "react";

import type { Skill } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { errorText } from "./pages-status.ts";
import { RevisionList } from "./RevisionList.tsx";

export type SkillEditorProps = {
  /** The skill being edited, or null for a new one. */
  skill: Skill | null;
  /** The message from the last save of this skill, kept by the page so it survives the move from new to edit. */
  notice: string | null;
  onSaved: (skill: Skill, message: string) => void;
  onEdited: () => void;
};

export function SkillEditor({ skill, notice, onSaved, onEdited }: SkillEditorProps) {
  const { client, labId, refresh } = useClient();
  const [title, setTitle] = useState(skill?.title ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [body, setBody] = useState(skill?.body ?? "");
  const [revision, setRevision] = useState(skill?.revision ?? 0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function edit(change: () => void) {
    change();
    setError(null);
    onEdited();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const saved = await client.saveSkill(labId, { id: skill?.id, title, description, body });
      // Identical content comes back as the revision that was already latest.
      const same = skill !== null && saved.revision === revision;
      setRevision(saved.revision);
      refresh();
      onSaved(saved, same ? "No changes to save." : `Saved as revision ${saved.revision}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  const ready = title.trim() !== "" && body.trim() !== "";
  return (
    <form className="pg-form" onSubmit={onSubmit} aria-label={skill ? "Edit skill" : "New skill"}>
      <label className="pg-field">
        <span>Title</span>
        <input value={title} onChange={(e) => edit(() => setTitle(e.target.value))} />
      </label>
      <label className="pg-field">
        <span>Description</span>
        <input value={description} onChange={(e) => edit(() => setDescription(e.target.value))} />
      </label>
      <label className="pg-field">
        <span>Instructions (Markdown)</span>
        <textarea className="ext-mono" rows={10} value={body} onChange={(e) => edit(() => setBody(e.target.value))} />
      </label>
      <div className="pg-actions">
        <button type="submit" className="pg-button" disabled={pending || !ready}>Save skill</button>
        <span role="status" className="pg-note">{notice ?? ""}</span>
      </div>
      {error && <p role="alert" className="pg-error">{error}</p>}

      <section aria-labelledby="ext-preview-heading">
        <h3 id="ext-preview-heading">Preview</h3>
        <pre className="ext-preview" role="region" tabIndex={0} aria-label="Preview of the instructions">{body}</pre>
      </section>
      {skill && <RevisionList kind="skill" id={skill.id} />}
    </form>
  );
}
