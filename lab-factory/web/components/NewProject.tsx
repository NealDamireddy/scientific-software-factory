"use client";

import "./pages.css";

import { useState } from "react";
import type { FormEvent } from "react";

import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText } from "./pages-status.ts";

export function NewProject() {
  const { client, labId, refresh } = useClient();
  const [, navigate] = useRoute();
  const [title, setTitle] = useState("");
  const [goals, setGoals] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const project = await client.createProject(labId, title.trim(), goals.trim());
      refresh();
      navigate({ view: "project", projectId: project.id });
    } catch (err) {
      setError(errorText(err));
      setPending(false);
    }
  }

  return (
    <form className="pg-form" onSubmit={onSubmit} aria-label="New project">
      <label className="pg-field">
        <span>Project title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="pg-field">
        <span>Goals</span>
        <textarea rows={3} value={goals} onChange={(e) => setGoals(e.target.value)} />
      </label>
      <div className="pg-actions">
        <button type="submit" className="pg-button" disabled={pending || title.trim() === "" || goals.trim() === ""}>
          Create project
        </button>
      </div>
      {error && <p role="alert" className="pg-error">{error}</p>}
    </form>
  );
}
