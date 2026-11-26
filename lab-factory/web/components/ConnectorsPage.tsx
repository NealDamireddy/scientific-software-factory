"use client";

import "./pages.css";
import "./extensions.css";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import type { Connector, ConnectorItem, DocumentTarget, Experiment, Project } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { errorText, kindLabel } from "./pages-status.ts";

type ProjectRow = Project & { experiments: Pick<Experiment, "id" | "title">[] };
type Target = { value: string; title: string; target: DocumentTarget };
type ItemState = { target?: string; pending?: boolean; result?: string; error?: string };

/** Every project and experiment an item can be added to. */
function targetsOf(project: ProjectRow): { group: string; options: { label: string; entry: Target }[] } {
  return {
    group: project.title,
    options: [
      { label: `Project: ${project.title}`, entry: { value: `project:${project.id}`, title: project.title, target: { kind: "project", id: project.id } } },
      ...project.experiments.map((e) => ({
        label: e.title,
        entry: { value: `experiment:${e.id}`, title: e.title, target: { kind: "experiment" as const, id: e.id } },
      })),
    ],
  };
}

export function ConnectorsPage() {
  const { client, labId, mode, version, refresh } = useClient();
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [items, setItems] = useState<Record<string, ItemState>>({});
  const accountField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    Promise.all([client.listConnectors(labId), client.listProjects(labId)]).then(
      ([rows, projectRows]) => {
        if (!live) return;
        setConnectors(rows);
        setProjects(projectRows);
        setError(null);
      },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  useEffect(() => {
    if (connecting) accountField.current?.focus();
  }, [connecting]);

  const groups = projects.map(targetsOf);
  const targets = groups.flatMap((g) => g.options.map((o) => o.entry));
  // Connected connectors first; otherwise the catalog order.
  const ordered = connectors ? [...connectors.filter((c) => c.connected), ...connectors.filter((c) => !c.connected)] : [];

  function openConnect(id: string) {
    setConnecting(id);
    setAccount("");
    setError(null);
  }

  async function onConnect(e: FormEvent, connector: Connector) {
    e.preventDefault();
    if (busy || account.trim() === "") return;
    setBusy(connector.id);
    setError(null);
    try {
      await client.connect(labId, connector.id, account.trim());
      setConnecting(null);
      refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function onDisconnect(connector: Connector) {
    if (busy) return;
    setBusy(connector.id);
    setError(null);
    try {
      await client.disconnect(labId, connector.id);
      if (connecting === connector.id) setConnecting(null);
      refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  function patchItem(key: string, change: ItemState) {
    setItems((all) => ({ ...all, [key]: { ...all[key], ...change } }));
  }

  async function onAdd(connector: Connector, item: ConnectorItem) {
    const key = `${connector.id}/${item.id}`;
    if (items[key]?.pending) return;
    const chosen = targets.find((t) => t.value === (items[key]?.target ?? targets[0]?.value));
    if (!chosen) return;
    patchItem(key, { pending: true, result: undefined, error: undefined });
    try {
      const revision = await client.importFromConnector(labId, connector.id, item.id, chosen.target);
      patchItem(key, { pending: false, result: `Added to ${chosen.title} as revision ${revision.number}` });
      refresh();
    } catch (err) {
      patchItem(key, { pending: false, error: errorText(err) });
    }
  }

  return (
    <div className="page pg-page ext-page">
      <h1>Connectors</h1>
      <p className="ext-intro">
        Connect the tools your lab already uses. Items from connected tools can be added to a project or an experiment as sources.
      </p>
      {mode === "sample" && <p className="ext-note">Connections here are simulated.</p>}

      {error && <p role="alert" className="pg-error ext-error">{error}</p>}
      {!connectors && !error && <p className="pg-note">Loading</p>}

      {ordered.map((c) => (
        <section key={c.id} className="ext-connector" aria-labelledby={`ext-${c.id}`}>
          <h2 id={`ext-${c.id}`}>{c.name}</h2>
          <p>{c.provides}</p>
          <p className="ext-status">{c.connected ? `Connected as ${c.account}` : "Not connected"}</p>

          <div className="ext-connector-actions">
            {connecting === c.id ? (
              <form className="ext-connect-form" onSubmit={(e) => onConnect(e, c)} aria-label={`Connect ${c.name}`}>
                <label className="pg-field">
                  <span>Account or folder name</span>
                  <input ref={accountField} value={account} onChange={(e) => setAccount(e.target.value)} />
                </label>
                <button type="submit" className="pg-button" aria-label={`Connect ${c.name}`}
                  disabled={busy !== null || account.trim() === ""}>
                  Connect
                </button>
                <button type="button" className="pg-button pg-quiet" disabled={busy !== null} onClick={() => setConnecting(null)}>
                  Cancel
                </button>
              </form>
            ) : c.connected ? (
              <button type="button" className="pg-button pg-quiet" aria-label={`Disconnect ${c.name}`}
                disabled={busy !== null} onClick={() => onDisconnect(c)}>
                Disconnect
              </button>
            ) : (
              <button type="button" className="pg-button" aria-label={`Connect ${c.name}`}
                disabled={busy !== null} onClick={() => openConnect(c.id)}>
                Connect
              </button>
            )}
          </div>

          {c.connected && c.items.length > 0 && (
            <ul className="ext-items" aria-label={`Items from ${c.name}`}>
              {c.items.map((item) => {
                const key = `${c.id}/${item.id}`;
                const state = items[key] ?? {};
                return (
                  <li key={item.id} className="ext-item">
                    <span className="ext-item-text">
                      <span className="ext-item-title">{item.title}</span>
                      <span className="ext-note">{item.kind === "readings" ? "Readings" : item.kind === "code" ? "Code" : kindLabel(item.kind)}</span>
                    </span>
                    {item.kind === "readings" ? (
                      <span className="pg-note">Available in the Results tab.</span>
                    ) : targets.length === 0 ? (
                      <span className="pg-note">Create a project first.</span>
                    ) : (
                      <span className="ext-item-add">
                        <label className="pg-field">
                          <span>Add to</span>
                          <select
                            aria-label={`Add to, ${item.title}`}
                            value={state.target ?? targets[0].value}
                            onChange={(e) => patchItem(key, { target: e.target.value, result: undefined, error: undefined })}
                          >
                            {groups.map((g) => (
                              <optgroup key={g.group} label={g.group}>
                                {g.options.map((o) => <option key={o.entry.value} value={o.entry.value}>{o.label}</option>)}
                              </optgroup>
                            ))}
                          </select>
                        </label>
                        <button type="button" className="pg-button" aria-label={`Add ${item.title}`}
                          disabled={state.pending === true} onClick={() => onAdd(c, item)}>
                          Add
                        </button>
                      </span>
                    )}
                    {state.result && <p role="status" className="ext-result">{state.result}</p>}
                    {state.error && <p role="alert" className="pg-error ext-result">{state.error}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
