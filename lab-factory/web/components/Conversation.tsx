"use client";

import { useLayoutEffect, useRef } from "react";

import type { ActivityItem, Message, OutputKind, OutputRef } from "../lib/types.ts";
import { ActivityLog } from "./ActivityLog.tsx";
import { OutputRefCard } from "./OutputRefCard.tsx";
import { ProposalCard } from "./ProposalCard.tsx";

/** Activity streaming in for a call still in flight, shown under the message that started it. */
export type LiveActivity = { anchor: string; items: ActivityItem[] };
/** The person's message while its send is in flight, before the stored copy comes back. */
export type Echo = { text: string; attachments: string[] };
/** The anchor of live activity that belongs to the echo rather than to a stored message. */
export const ECHO_ANCHOR = "echo";

// Within this distance of the bottom, the conversation follows new content.
const FOLLOW_PX = 80;

function Attachments({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <ul className="conv-attachments" aria-label="Attachments">
      {names.map((name, i) => <li key={`${i}-${name}`} className="conv-attachment">{name}</li>)}
    </ul>
  );
}

function PersonMessage({ text, attachments }: Echo) {
  return (
    <div className="conv-person">
      <span className="visually-hidden">You: </span>
      {text !== "" ? <p className="conv-text">{text}</p> : null}
      <Attachments names={attachments} />
    </div>
  );
}

export function Conversation({ messages, live, echo, fresh, busy, onBuild, onOpenOutput }: {
  messages: Message[];
  live: LiveActivity | null;
  echo: Echo | null;
  /** Messages that arrived from a call made here: their activity starts open. */
  fresh: ReadonlySet<string>;
  busy: boolean;
  onBuild: (messageId: string, outputs: OutputKind[]) => Promise<void>;
  onOpenOutput: (output: OutputRef) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const liveLog = (anchor: string) =>
    live && live.anchor === anchor && live.items.length > 0 ? <ActivityLog key={`live-${anchor}`} items={live.items} live /> : null;

  // Keep the newest message and activity line in view, unless the person scrolled up to read.
  const contentKey = `${messages.length}:${messages.at(-1)?.id ?? ""}:${live?.items.length ?? -1}:${echo ? 1 : 0}`;
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [contentKey]);

  return (
    <div
      ref={scroller}
      className="conv-scroll"
      onScroll={(e) => {
        const el = e.currentTarget;
        follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_PX;
      }}
    >
      <ol className="conv-list" aria-label="Conversation">
        {messages.map((message) => (
          <li key={message.id} className={message.from === "person" ? "conv-message conv-message-person" : "conv-message"}>
            {message.from === "person" ? (
              <PersonMessage text={message.text} attachments={message.attachments ?? []} />
            ) : (
              <div className="conv-factory">
                <span className="visually-hidden">Factory: </span>
                {message.text !== "" ? <p className="conv-text">{message.text}</p> : null}
                {message.proposal ? (
                  <ProposalCard
                    proposal={message.proposal}
                    busy={busy}
                    onBuild={(outputs) => onBuild(message.id, outputs)}
                  />
                ) : null}
                {message.activity && message.activity.length > 0 ? (
                  <ActivityLog items={message.activity} open={fresh.has(message.id)} />
                ) : null}
                {message.output_refs && message.output_refs.length > 0 ? (
                  <ul className="conv-refs" aria-label="Outputs built">
                    {message.output_refs.map((ref, i) => (
                      <li key={`${ref.kind}-${i}`}><OutputRefCard output={ref} onOpen={onOpenOutput} /></li>
                    ))}
                  </ul>
                ) : null}
                {liveLog(message.id)}
              </div>
            )}
          </li>
        ))}
        {echo ? (
          <li className="conv-message conv-message-person">
            <PersonMessage text={echo.text} attachments={echo.attachments} />
          </li>
        ) : null}
        {echo && live?.anchor === ECHO_ANCHOR && live.items.length > 0 ? (
          <li className="conv-message">
            <div className="conv-factory">
              <span className="visually-hidden">Factory: </span>
              {liveLog(ECHO_ANCHOR)}
            </div>
          </li>
        ) : null}
      </ol>
    </div>
  );
}
