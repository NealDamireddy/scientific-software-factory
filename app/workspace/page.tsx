"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Blocks,
  ChevronRight,
  FolderOpen,
  LayoutGrid,
  SlidersHorizontal,
  FlaskConical,
  LogOut,
  RefreshCw,
} from "lucide-react";
import { createLiveClient, WorkspaceError } from "./api";
import type { FieldErrors, Mode, Snapshot, WorkspaceClient } from "./api";
import { createFixtureClient } from "./fixture";
import ProjectDirectory, { Archives, projectName } from "./ProjectDirectory";
import RefineData from "./RefineData";
import Editors from "./Editors";
import RunViews from "./RunViews";
import "./workspace.css";

type Scope = { mode: Mode; projectId: string };
type Tab = "runs" | "context" | "specification" | "refine";
type Fault = "unauthenticated" | "expired" | "forbidden" | "unavailable";
const preview = process.env.NEXT_PUBLIC_FIXTURE_PREVIEW === "1";
// The live workspace needs a service. Until one is configured for this build,
// the option is disabled instead of calling an endpoint that nothing serves.
const liveApiUrl = (process.env.NEXT_PUBLIC_WORKSPACE_API_URL || "").trim();
const liveUnavailable = preview
  ? "Live access is unavailable in this preview."
  : !liveApiUrl
    ? "Live workspace is not available yet: no workspace service is configured for this site. Use demo data instead."
    : "";
const tabs = [
  ["specification", "Build application", Blocks],
  ["refine", "Refine data", SlidersHorizontal],
  ["runs", "Runs", Activity],
  ["context", "Lab & project", FolderOpen],
] as const;

function ProjectWorkspace({
  client,
  projectId,
  mode,
}: Scope & { client: WorkspaceClient }) {
  const [tab, setTab] = useState<Tab>("runs");
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState("");
  const [readMessage, setReadMessage] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [stale, setStale] = useState(false);
  const [denied, setDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = useRef(false);
  const version = useRef(0);
  const writing = useRef(false);
  const readsPending = useRef(0);
  const accessLost = useRef(false);

  const fail = useCallback((cause: unknown, fromRead: boolean) => {
    if (cause instanceof WorkspaceError && cause.accessDenied) {
      ++version.current;
      accessLost.current = true;
      setSnapshot(undefined);
      setDenied(true);
      setErrors({});
      setReadMessage("");
      setStale(false);
      setError(
        cause.status === 403
          ? "Access denied for this project."
          : cause.code === "expired" || cause.code === "session_expired"
            ? "Session expired. Reopen the workspace after signing in."
            : "Authentication required. Sign in to the workspace service and retry.",
      );
      return;
    }
    const report = fromRead ? setReadMessage : setError;
    report(
      cause instanceof WorkspaceError
        ? cause.message
        : "The workspace service could not complete this request.",
    );
    if (fromRead || !(cause instanceof WorkspaceError) || cause.status >= 500)
      setStale(true);
    if (!fromRead)
      setErrors(cause instanceof WorkspaceError ? cause.fields : {});
  }, []);

  const read = useCallback(
    async (clearMessage = false) => {
      const id = ++version.current;
      ++readsPending.current;
      try {
        const next = await client.read(projectId);
        if (!active.current || id !== version.current) return;
        setSnapshot(next);
        setDenied(false);
        accessLost.current = false;
        setStale(false);
        setReadMessage("");
        if (clearMessage) setError("");
      } catch (cause) {
        if (
          active.current &&
          (id === version.current ||
            (cause instanceof WorkspaceError && cause.accessDenied))
        ) {
          fail(cause, true);
        }
      } finally {
        --readsPending.current;
      }
    },
    [client, projectId, fail],
  );

  useEffect(() => {
    active.current = true;
    void read(true);
    const timer = window.setInterval(() => {
      if (
        !writing.current &&
        !readsPending.current &&
        !accessLost.current &&
        document.visibilityState === "visible"
      )
        void read();
    }, 10000);
    return () => {
      active.current = false;
      ++version.current;
      window.clearInterval(timer);
    };
  }, [read]);

  async function operate<T>(
    action: () => Promise<T>,
    refresh = true,
  ): Promise<T | undefined> {
    if (writing.current || accessLost.current) return;
    writing.current = true;
    ++version.current;
    setBusy(true);
    setError("");
    setErrors({});
    try {
      const result = await action();
      if (!active.current || accessLost.current) return;
      if (refresh) await read();
      if (active.current && !accessLost.current) return result;
    } catch (cause) {
      if (active.current) fail(cause, false);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <>
      <div className="ws-bar">
        <nav aria-label="Workspace views">
          {tabs.map(([value, name, Icon]) => (
            <button
              key={value}
              aria-current={tab === value ? "page" : undefined}
              onClick={() => setTab(value)}
            >
              <Icon size={16} /> {name}
            </button>
          ))}
        </nav>
        <button
          className="ws-refresh"
          disabled={busy}
          onClick={() => void read(true)}
        >
          <RefreshCw size={15} /> Refresh workspace
        </button>
      </div>
      {(error || readMessage) && (
        <div role="alert" className="ws-alert">
          {error || readMessage}
          {Object.keys(errors).length > 0 && (
            <ul>
              {Object.entries(errors).map(([field, reason]) => (
                <li key={field}>
                  <b>{field}</b> · {reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {stale && !denied && (
        <p role="status" className="ws-alert">
          {snapshot
            ? `Stale progress · Last recorded ${snapshot.recorded_at}. Showing saved records.`
            : `${mode === "live" ? "Live execution" : "Demo service"} unavailable. Retry to load this workspace.`}
        </p>
      )}
      {!snapshot && !error && !readMessage && (
        <p role="status">Loading workspace…</p>
      )}
      {snapshot && !denied && (
        <>
          {!snapshot.specifications.length && !snapshot.runs.length && (
            <div className="ws-first">
              <FlaskConical size={22} />
              <div>
                <h2>Create your first experiment</h2>
                <p>
                  Review your lab and project, then draft and approve a
                  specification.
                </p>
              </div>
              <button onClick={() => setTab("specification")}>
                New specification
              </button>
            </div>
          )}
          <div hidden={tab !== "runs"}>
            <RunViews demo={mode === "fixture"} {...{ snapshot, client, projectId, operate, stale }} />
          </div>
          {tab === "refine" && <RefineData runs={snapshot.runs} />}
          <fieldset
            className="ws-editor"
            hidden={tab !== "context" && tab !== "specification"}
            disabled={busy}
          >
            <Editors editProject={() => setTab("context")}
              {...{ snapshot, client, projectId, operate, errors }}
              section={tab === "context" ? "context" : "specification"}
            />
          </fieldset>
        </>
      )}
    </>
  );
}

export default function Workspace() {
  const [scope, setScope] = useState<Scope>();
  const [projectInput, setProjectInput] = useState("");
  const [ended, setEnded] = useState(false);
  const [ending, setEnding] = useState(false);
  const [sessionMessage, setSessionMessage] = useState("");
  const [fault, setFault] = useState<Fault | "">("");
  const faultRef = useRef<Fault | "">("");
  function setResponse(value: Fault | "") {
    faultRef.current = value;
    setFault(value);
  }
  useEffect(() => {
    function syncLocation() {
      const params = new URLSearchParams(window.location.search);
      const mode = params.get("mode") === "live" ? "live" : "fixture";
      const projectId = params.get("project") || "";
      setScope({mode, projectId});
      setProjectInput(projectId);
      setResponse("");
    }
    syncLocation();
    window.addEventListener("popstate", syncLocation);
    return () => window.removeEventListener("popstate", syncLocation);
  }, []);
  function open(next: Scope) {
    setSessionMessage("");
    setResponse("");
    setScope(next);
    setProjectInput(next.projectId);
    const url = new URL(window.location.href);
    url.searchParams.set("mode", next.mode);
    url.searchParams.set("project", next.projectId);
    window.history.pushState(null, "", url);
  }
  const mode = scope?.mode;
  const client = useMemo(
    () =>
      mode !== "live" || liveUnavailable
        ? createFixtureClient({ fault: () => faultRef.current || undefined })
        : createLiveClient(liveApiUrl),
    [mode, ended],
  );

  async function endSession() {
    setEnding(true);
    setEnded(true);
    setSessionMessage("");
    try {
      await client.endSession();
    } catch {
      setSessionMessage(
        "Local workspace cleared. The service could not confirm sign-out.",
      );
    } finally {
      setEnding(false);
    }
  }
  return (
    <div className="workspace">
      <header className="ws-top"><div>
        <a className="ws-brand" href="/"><FlaskConical size={24}/> EVOLVE</a>
        <span className="ws-lab">UV–Vis laboratory</span>
        {scope && !ended && <button className="ws-end" onClick={() => void endSession()}><LogOut size={15}/> End session</button>}
      </div></header>
      <main>
        <nav className="breadcrumb" aria-label="Breadcrumb"><LayoutGrid size={15}/><a href={mode === "live" ? "/workspace/?mode=live" : "/"}>Lab projects</a>
          {scope?.projectId && <><ChevronRight size={14}/><span>{mode === "fixture" ? projectName(scope.projectId) : scope.projectId}</span></>}
        </nav>
        {preview && <details><summary>Build details</summary><p>Preview commit <code>{process.env.NEXT_PUBLIC_PREVIEW_COMMIT || "unavailable"}</code></p></details>}
        {ended ? (
          <section className="workspace-card">
            <h2>Session closed</h2>
            <p>
              {sessionMessage ||
                "Project records have been cleared from this view."}
            </p>
            <button
              disabled={ending}
              onClick={() => {
                setEnded(false);
                setResponse("");
              }}
            >
              Reopen workspace
            </button>
          </section>
        ) : (
          scope && (
            <>
              <div className="directory-heading">
                <div><h1>{scope.projectId ? (mode === "fixture" ? projectName(scope.projectId) : scope.projectId) : "Lab projects"}</h1>
                  <p>{scope.projectId ? (mode === "fixture" ? "Demo workspace · Changes apply only to this demo session." : "Authenticated workspace") : "Choose a project to build an application or work with its data."}</p></div>
                <label className="data-source">Data source<select value={scope.mode} onChange={e => open({mode:e.target.value as Mode, projectId:""})}>
                  <option value="fixture">Demo data</option><option value="live" disabled={!!liveUnavailable}>Live workspace{liveUnavailable ? " (not available)" : ""}</option>
                </select></label>
              </div>
              {scope.mode === "fixture" && !scope.projectId && <><ProjectDirectory/><Archives/></>}
              {scope.mode === "live" && (liveUnavailable ? <p role="status">{liveUnavailable}</p> :
                <form className="live-project" onSubmit={e => {e.preventDefault(); if(projectInput.trim()) open({mode:"live",projectId:projectInput.trim()});}}>
                  <label>Project ID<input required value={projectInput} onChange={e => setProjectInput(e.target.value)}/></label>
                  <button>Open project</button>
                </form>)}
              {scope.projectId && !(liveUnavailable && mode === "live") && (
                <ProjectWorkspace
                  key={scope.mode + "/" + scope.projectId}
                  client={client}
                  {...scope}
                />
              )}
              {scope.mode === "fixture" && scope.projectId && (
                <details className="ws-controls">
                  <summary>Demo controls</summary>
                  <label>Project<select value={scope.projectId} onChange={e => open({...scope, projectId:e.target.value})}>
                    <option value="visible-assay">Visible absorbance assay</option><option value="empty-assay">Assay development</option><option value="foreign-project">Restricted project</option>
                  </select></label>
                  <label>
                    Response to next requests
                    <select
                      value={fault}
                      onChange={(e) =>
                        setResponse(e.target.value as Fault | "")
                      }
                    >
                      <option value="">Normal response</option>
                      <option value="unauthenticated">Unauthenticated</option>
                      <option value="expired">Expired session</option>
                      <option value="forbidden">Forbidden project</option>
                      <option value="unavailable">Service unavailable</option>
                    </select>
                  </label>
                </details>
              )}
            </>
          )
        )}
      </main>
    </div>
  );
}
