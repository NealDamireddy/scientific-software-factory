"use client";

import "./workspace.css";

import { PanelRightOpen } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";

import { routeHref } from "../lib/route.ts";
import { errorText } from "../lib/status.ts";
import type { ActivityItem, Message, OnActivity, OutputKind, OutputRef, Workspace as WorkspaceData } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { Composer } from "./Composer.tsx";
import { Conversation, ECHO_ANCHOR } from "./Conversation.tsx";
import { ExperimentContext, ExperimentContextToggle } from "./ExperimentContext.tsx";
import type { Echo, LiveActivity } from "./Conversation.tsx";
import { OutputPanel, availableTabs } from "./OutputPanel.tsx";
import { RunnerProvider } from "./RunnerContext.tsx";
import type { PanelTab } from "./OutputPanel.tsx";
import type { ShowOrderRequest } from "./SubmissionPanel.tsx";

/** One experiment: its conversation with the factory, and the outputs it built beside it. */
export function Workspace({ projectId, experimentId }: { projectId: string; experimentId: string }) {
  // Keyed, so moving to another experiment starts from a clean slate (panel, drafts, live activity).
  // The Python runner sits above the key: its loaded runtime serves every experiment visited.
  return (
    <RunnerProvider>
      <ExperimentWorkspace key={experimentId} projectId={projectId} experimentId={experimentId} />
    </RunnerProvider>
  );
}

/** A call to the factory in flight: what it shows until the stored messages come back. */
type InFlight = { live: LiveActivity; echo: Echo | null; /** Stored messages shown meanwhile. */ cutoff: number };

/**
 * What each experiment has in flight, kept outside the keyed workspace so leaving an experiment
 * mid-build and coming back still shows the work, and one experiment's state never shows in another.
 */
type Entry = { inFlight: InFlight | null; fresh: ReadonlySet<string> };
const NO_ENTRY: Entry = { inFlight: null, fresh: new Set() };
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();

function updateEntry(id: string, change: (entry: Entry) => Entry) {
  entries.set(id, change(entries.get(id) ?? NO_ENTRY));
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function ExperimentWorkspace({ projectId, experimentId }: { projectId: string; experimentId: string }) {
  const { client, version, refresh } = useClient();
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Only the newest fetch may land, so an older, slower one never overwrites newer data.
  const fetchSeq = useRef(0);

  const { inFlight, fresh } = useSyncExternalStore(
    subscribe,
    () => entries.get(experimentId) ?? NO_ENTRY,
    () => NO_ENTRY,
  );

  const [closed, setClosed] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const contextId = useId();
  const [tab, setTab] = useState<PanelTab | null>(null);
  const [orderRequest, setOrderRequest] = useState<ShowOrderRequest | null>(null);
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
    return (item: ActivityItem) => updateEntry(experimentId, (entry) => {
      const current = entry.inFlight;
      if (!current || current.live.anchor !== anchor || current.live.items.some((i) => i.id === item.id)) return entry;
      return { ...entry, inFlight: { ...current, live: { anchor, items: [...current.live.items, item] } } };
    });
  }

  /** Runs one call to the factory, then renders from the stored workspace so nothing shows twice. */
  async function act(start: Omit<InFlight, "cutoff">, call: (onActivity: OnActivity) => Promise<Message[]>) {
    if ((entries.get(experimentId) ?? NO_ENTRY).inFlight || !data) return;
    updateEntry(experimentId, (entry) => ({ ...entry, inFlight: { ...start, cutoff: data.messages.length } }));
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
    updateEntry(experimentId, (entry) => ({
      inFlight: null,
      fresh: added.length > 0 ? new Set([...entry.fresh, ...added.map((m) => m.id)]) : entry.fresh,
    }));
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

  function openOutput(output: OutputRef) {
    const { kind, work_order_id: workOrderId } = output;
    setClosed(false);
    setTab(kind);
    if (workOrderId && (kind === "procedure" || kind === "run_plan")) {
      setOrderRequest((last) => ({ kind, workOrderId, nonce: (last?.nonce ?? 0) + 1 }));
    }
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
          <div className="ws-header-actions">
            <ExperimentContextToggle open={contextOpen} controls={contextId} onToggle={() => setContextOpen((o) => !o)} />
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
          </div>
        </header>
        {contextOpen && <ExperimentContext id={contextId} experiment={data.experiment} />}
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
            orderRequest={orderRequest}
            onClose={() => { setClosed(true); focusNext.current = "show"; }}
          />
        </div>
      ) : null}
    </div>
  );
}
