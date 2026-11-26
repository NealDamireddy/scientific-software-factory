"use client";

import "./pages.css";

import { useId, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import type { Document, DocumentTarget } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { DOCUMENT_KINDS, errorText } from "./pages-status.ts";

export function AddDocument({ target }: { target: DocumentTarget }) {
  const { client, refresh } = useClient();
  const uid = useId();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<Document["kind"]>("sop");
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ number: number; same: boolean } | null>(null);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const content = await file.text();
      setText(content);
      setTitle((t) => (t.trim() === "" ? file.name.replace(/\.(txt|md)$/i, "") : t));
      setSaved(null);
      setError(null);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    setSaved(null);
    try {
      const before = await client.listRevisions(target.kind, target.id).catch(() => []);
      const latest = before[before.length - 1]?.number;
      const revision = await client.addDocument(target, { title: title.trim(), kind, text });
      // Identical title and text comes back as the revision that was already latest.
      setSaved({ number: revision.number, same: revision.number === latest });
      setTitle("");
      setText("");
      refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  const ready = title.trim() !== "" && text.trim() !== "";
  return (
    <form className="pg-form" onSubmit={onSubmit} aria-label="Add a document">
      <label className="pg-field">
        <span>Title</span>
        <input value={title} onChange={(e) => { setTitle(e.target.value); setSaved(null); }} />
      </label>
      <label className="pg-field">
        <span>Kind</span>
        <select value={kind} onChange={(e) => setKind(e.target.value as Document["kind"])}>
          {DOCUMENT_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </label>
      <label className="pg-field">
        <span>Text</span>
        <textarea rows={5} value={text} onChange={(e) => { setText(e.target.value); setSaved(null); }} />
      </label>
      <div className="pg-field">
        <label htmlFor={`${uid}-file`} className="pg-note">Or fill it from a .txt or .md file</label>
        <input id={`${uid}-file`} type="file" accept=".txt,.md,text/plain,text/markdown" onChange={onFile} />
      </div>
      <div className="pg-actions">
        <button type="submit" className="pg-button" disabled={!ready || pending}>Add document</button>
        {saved !== null && <span role="status" className="pg-note">{saved.same ? `Already saved as revision ${saved.number}` : `Saved as revision ${saved.number}`}</span>}
      </div>
      {error && <p role="alert" className="pg-error">{error}</p>}
    </form>
  );
}
