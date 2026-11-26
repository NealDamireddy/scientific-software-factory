"use client";

import "./pages.css";
import "./extensions.css";

import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { AgentConnection, AgentSetup } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { CopyField } from "./CopyField.tsx";
import { errorText, formatDate } from "./pages-status.ts";

type Loaded = {
  setup: AgentSetup;
  agents: AgentConnection[];
  /** Work order id to the experiment it belongs to. */
  orders: Record<string, { projectId: string; experimentId: string; title: string }>;
};

/** The static copy the app ships: what sample mode serves as the SKILL.md. */
const SKILL_HREF = "/skills/labfactory-work-orders/SKILL.md";

/**
 * In live mode the download is built from the service's `skill_md`, so it is exactly the text shown
 * under `Show SKILL.md`. Sample mode links the shipped file, which is the same text.
 */
function useSkillHref(live: boolean, text: string | undefined): string {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!live || text === undefined) return;
    const made = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    setUrl(made);
    return () => { URL.revokeObjectURL(made); setUrl(null); };
  }, [live, text]);
  return live && url ? url : SKILL_HREF;
}

export function AgentsPage() {
  const { client, labId, mode, version } = useClient();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      const [setup, agents, projects] = await Promise.all([
        client.getAgentSetup(labId), client.listAgentConnections(labId), client.listProjects(labId),
      ]);
      // Each experiment's workspace names its work orders; an order we can't place is shown as plain text.
      const orders: Loaded["orders"] = {};
      if (agents.length > 0) {
        const experiments = projects.flatMap((p) => p.experiments.map((e) => ({ projectId: p.id, ...e })));
        await Promise.all(experiments.map((e) => client.getWorkspace(e.id).then((w) => {
          for (const view of [w.procedure, w.run_plan]) {
            if (view) orders[view.order.id] = { projectId: e.projectId, experimentId: e.id, title: e.title };
          }
        }, () => undefined)));
      }
      if (live) { setLoaded({ setup, agents, orders }); setError(null); }
    })().catch((e: unknown) => { if (live) setError(errorText(e)); });
    return () => { live = false; };
  }, [client, labId, version]);

  const skillHref = useSkillHref(mode === "live", loaded?.setup.skill_md);

  return (
    <div className="page pg-page ext-page">
      <h1>Connect your agent</h1>
      <p className="ext-intro">
        Let your own coding agent pick up this lab&apos;s work orders. It gets the lab&apos;s context and skills, and its work goes through the same checks.
      </p>

      {error && <p role="alert" className="pg-error ext-error">{error}</p>}
      {!loaded && !error && <p className="pg-note">Loading</p>}
      {loaded && (
        <>
          <section className="pg-section" aria-labelledby="ext-mcp">
            <h2 id="ext-mcp">Via MCP</h2>
            <CopyField label="Claude Code" value={loaded.setup.claude_code} language="shell" />
            <CopyField label="Codex (~/.codex/config.toml)" value={loaded.setup.codex_toml} language="toml" />
            <CopyField label="Cursor (.cursor/mcp.json)" value={loaded.setup.cursor_json} language="json" />
            <p className="ext-note">Use absolute paths to your Lab Factory checkout and your lab&apos;s database.</p>
            <div className="ext-table-wrap">
              <table className="ext-table">
                <caption>MCP tools</caption>
                <thead>
                  <tr><th scope="col">Tool</th><th scope="col">What it does</th></tr>
                </thead>
                <tbody>
                  {loaded.setup.tools.map((t) => (
                    <tr key={t.name}><td>{t.name}</td><td>{t.description}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="pg-section" aria-labelledby="ext-skill">
            <h2 id="ext-skill">As a skill</h2>
            <div className="ext-actions-row">
              <a className="pg-button ext-link" href={skillHref} download="SKILL.md">Download SKILL.md</a>
            </div>
            <details className="ext-details">
              <summary>Show SKILL.md</summary>
              <CopyField label="SKILL.md" value={loaded.setup.skill_md} language="markdown" />
            </details>
          </section>

          <section className="pg-section" aria-labelledby="ext-agents">
            <h2 id="ext-agents">Connected agents</h2>
            {loaded.agents.length === 0 && <p className="pg-note">No agents have claimed work yet.</p>}
            {loaded.agents.length > 0 && (
              <ul className="pg-list">
                {loaded.agents.map((a) => (
                  <li key={a.worker} className="ext-agent">
                    <span className="ext-agent-name">{a.worker}</span>
                    <p className="pg-note">Last seen {formatDate(a.last_seen)}</p>
                    <ul className="ext-orders" aria-label={`Work orders claimed by ${a.worker}`}>
                      {a.work_order_ids.map((id) => {
                        const place = loaded.orders[id];
                        return (
                          <li key={id}>
                            {place
                              ? <a href={routeHref({ view: "experiment", projectId: place.projectId, experimentId: place.experimentId })}
                                  title={place.title}>{id}</a>
                              : <span>{id}</span>}
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="pg-section" aria-labelledby="ext-can">
            <h2 id="ext-can">What agents can and can&apos;t do</h2>
            <p>Agents can claim work and submit it for checks. Only a person can sign off a submission.</p>
          </section>
        </>
      )}
    </div>
  );
}
