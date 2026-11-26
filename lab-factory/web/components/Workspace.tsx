"use client";

import "./workspace.css";

import { PanelRightOpen } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { ActivityItem, Message, OnActivity, OutputKind, Workspace as WorkspaceData } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { Composer } from "./Composer.tsx";
import { Conversation, ECHO_ANCHOR } from "./Conversation.tsx";
import type { Echo, LiveActivity } from "./Conversation.tsx";
import { OutputPanel, availableTabs } from "./OutputPanel.tsx";
import type { PanelTab } from "./OutputPanel.tsx";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** One experiment: its conversation with the factory, and the outputs it built beside it. */
export function Workspace({ projectId, experimentId }: { projectId: string; experimentId: string }) {
  // Keyed, so moving to another experiment starts from a clean slate (panel, drafts, live activity).
  return <ExperimentWorkspace key={experimentId} projectId={projectId} experimentId={experimentId} />;
}

/** A call to the factory in flight: what it shows until the stored messages come back. */
type InFlight = { live: LiveActivity; echo: Echo | null; /** Stored messages shown meanwhile. */ cutoff: number };

function ExperimentWorkspace({ projectId, experimentId }: { projectId: string; experimentId: string }) {
  const { client, version, refresh } = useClient();
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Only the newest fetch may land, so an older, slower one never overwrites newer data.
  const fetchSeq = useRef(0);

  const [inFlight, setInFlight] = useState<InFlight | null>(null);
  const busyRef = useRef(false);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());

  const [closed, setClosed] = useState(false);
  const [tab, setTab] = useState<PanelTab | null>(null);
  const focusNext = useRef<"show" | "tab" | null>(null);
  const showButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const mine = ++fetchSeq.current;
    client.getWorkspace(experimentId).then(
      (ws) => {
        if (mine !== fetchSeq.current) return;
        setData(ws);
        setLoadError(null);
      },
      (e: unknown) => {
        if (mine === fetchSeq.current) setLoadError(errorText(e));
      },
    );
  }, [client, experimentId, version]);

  const tabs = data ? availableTabs(data) : [];
  const hasOutputs = tabs.length > 0;
  const open = hasOutputs && !closed;
  const shownTab = tab && tabs.includes(tab) ? tab : tabs[0];

  useLayoutEffect(() => {
    const target = focusNext.current;
    focusNext.current = null;
    if (target === "show") showButton.current?.focus();
    if (target === "tab" && shownTab) document.getElementById(`panel-tab-${shownTab}`)?.focus();
  });

  /** Streams activity into the in-flight log, once per item id. */
  function collect(anchor: string): OnActivity {
    return (item: ActivityItem) => setInFlight((current) => {
      if (!current || current.live.anchor !== anchor || current.live.items.some((i) => i.id === item.id)) return current;
      return { ...current, live: { anchor, items: [...current.live.items, item] } };
    });
  }

  /** Runs one call to the factory, then renders from the stored workspace so nothing shows twice. */
  async function act(start: Omit<InFlight, "cutoff">, call: (onActivity: OnActivity) => Promise<Message[]>) {
    if (busyRef.current || !data) return;
    busyRef.current = true;
    setInFlight({ ...start, cutoff: data.messages.length });
    let added: Message[] = [];
    let failure: unknown = null;
    try {
      added = await call(collect(start.live.anchor));
    } catch (e) {
      failure = e;
    }
    const mine = ++fetchSeq.current;
    try {
      const ws = await client.getWorkspace(experimentId);
      if (mine === fetchSeq.current) setData(ws);
    } catch (e) {
      if (mine === fetchSeq.current) setLoadError(errorText(e));
    }
    setInFlight(null);
    if (added.length > 0) setFresh((current) => new Set([...current, ...added.map((m) => m.id)]));
    busyRef.current = false;
    // The sidebar's status dots and the attention badge follow the new orders.
    refresh();
    if (failure !== null) throw failure;
  }

  function build(messageId: string, outputs: OutputKind[]): Promise<void> {
    return act({ live: { anchor: messageId, items: [] }, echo: null },
      (onActivity) => client.confirmPlan(experimentId, messageId, outputs, onActivity));
  }

  function send(text: string, files: File[]): Promise<void> {
    const echo: Echo = { text: text.trim(), attachments: files.map((f) => f.name.trim() || "Attachment") };
    return act({ live: { anchor: ECHO_ANCHOR, items: [] }, echo },
      (onActivity) => client.sendMessage(experimentId, text, files, onActivity));
  }

  function openOutput(kind: OutputKind) {
    setClosed(false);
    setTab(kind);
    focusNext.current = "tab";
  }

  if (!data) {
    if (loadError) return <div className="page"><p role="alert">Couldn&apos;t open this experiment: {loadError}</p></div>;
    return null;
  }

  const messages = inFlight ? data.messages.slice(0, inFlight.cutoff) : data.messages;

  return (
    <div className={open ? "ws ws-open" : "ws"}>
      <div className="ws-main">
        <header className="ws-header">
          <div className="ws-crumbs">
            <a className="ws-crumb-project" href={routeHref({ view: "project", projectId })}>{data.project.title}</a>
            <span className="ws-crumb-sep">/</span>
            <h1 className="ws-title">{data.experiment.title}</h1>
          </div>
          {hasOutputs && !open ? (
            <button
              ref={showButton}
              type="button"
              className="ws-button ws-show"
              onClick={() => { setClosed(false); focusNext.current = "tab"; }}
            >
              <PanelRightOpen size={18} aria-hidden="true" />
              <span>Show outputs</span>
            </button>
          ) : null}
        </header>
        {loadError ? <p className="ws-error ws-load-error" role="alert">{loadError}</p> : null}
        <Conversation
          messages={messages}
          live={inFlight?.live ?? null}
          echo={inFlight?.echo ?? null}
          fresh={fresh}
          busy={inFlight !== null}
          onBuild={build}
          onOpenOutput={openOutput}
        />
        <Composer busy={inFlight !== null} onSend={send} />
      </div>
      {hasOutputs && shownTab ? (
        <div className="ws-panel" data-open={open} inert={!open}>
          <OutputPanel
            workspace={data}
            tab={shownTab}
            onTab={setTab}
            onClose={() => { setClosed(true); focusNext.current = "show"; }}
          />
        </div>
      ) : null}
    </div>
  );
}
