"use client";

import "./pages.css";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { INITIAL_LOAD, canSaveSettings, settingsEditable, settingsLoad } from "../lib/settings.ts";
import type { SettingsLoad, SettingsLoadEvent } from "../lib/settings.ts";
import type { SignOffRule } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { errorText } from "./pages-status.ts";

export function SettingsPage() {
  const { client, labId, version, refresh } = useClient();
  const [mode, setMode] = useState<SignOffRule["mode"]>("anyone");
  const [names, setNames] = useState("");
  const [load, setLoad] = useState<SettingsLoad>(INITIAL_LOAD);
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = useRef(false);

  const loaded = settingsEditable(load);
  const step = (event: SettingsLoadEvent) => setLoad((state) => settingsLoad(state, event));

  useEffect(() => {
    let live = true;
    client.getSettings(labId).then(
      (s) => {
        if (!live || dirty.current) return;
        setMode(s.sign_off.mode);
        setNames(s.sign_off.mode === "listed" ? s.sign_off.names.join("\n") : "");
        step({ type: "loaded" });
      },
      (e: unknown) => { if (live) step({ type: "failed", error: errorText(e) }); },
    );
    return () => { live = false; };
  }, [client, labId, version, attempt]);

  function retry() {
    step({ type: "retry" });
    setAttempt((n) => n + 1);
  }

  function edit(change: () => void) {
    dirty.current = true;
    setSaved(false);
    setError(null);
    change();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSaveSettings(load, pending)) return;
    const list = names.split("\n").map((n) => n.trim()).filter((n) => n !== "");
    if (mode === "listed" && list.length === 0) {
      setError("Add at least one name, or choose anyone who gives their name.");
      return;
    }
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      await client.updateSettings(labId, { sign_off: mode === "listed" ? { mode: "listed", names: list } : { mode: "anyone" } });
      dirty.current = false;
      setSaved(true);
      refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="page pg-page">
      <h1>Lab settings</h1>
      {load.status === "failed" && (
        <div role="alert" className="pg-error pg-load-error">
          <span>Couldn&apos;t load the lab settings: {load.error}</span>
          <button type="button" className="pg-button pg-quiet" onClick={retry}>Try again</button>
        </div>
      )}
      <form className="pg-form" onSubmit={onSubmit} aria-label="Lab settings">
        <fieldset className="pg-field pg-choices">
          <legend>Who can sign off</legend>
          <label className="pg-choice">
            <input type="radio" name="sign-off" checked={mode === "anyone"} disabled={!loaded}
              onChange={() => edit(() => setMode("anyone"))} />
            <span>Anyone who gives their name</span>
          </label>
          <label className="pg-choice">
            <input type="radio" name="sign-off" checked={mode === "listed"} disabled={!loaded}
              onChange={() => edit(() => setMode("listed"))} />
            <span>Only these people</span>
          </label>
        </fieldset>
        {mode === "listed" && (
          <label className="pg-field">
            <span>Names, one per line</span>
            <textarea rows={5} value={names} disabled={!loaded} onChange={(e) => edit(() => setNames(e.target.value))} />
          </label>
        )}
        <div className="pg-actions">
          <button type="submit" className="pg-button" disabled={!canSaveSettings(load, pending)}>Save settings</button>
          {saved && <span role="status" className="pg-note">Settings saved</span>}
        </div>
        {error && <p role="alert" className="pg-error">{error}</p>}
      </form>
    </div>
  );
}
