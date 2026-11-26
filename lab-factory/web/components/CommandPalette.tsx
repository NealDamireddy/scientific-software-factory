"use client";

import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { SearchHit } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";

const KIND_LABEL: Record<SearchHit["kind"], string> = {
  project: "Project",
  experiment: "Experiment",
  document: "Document",
  instrument: "Instrument",
  skill: "Skill",
  connector: "Connector",
};

const DEBOUNCE_MS = 120;

/** Opens on Ctrl+K or Cmd+K anywhere, or when `open` is set by the Search button. */
export function CommandPalette({ open, onOpen, onClose }: { open: boolean; onOpen: () => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpen]);

  return open ? <PaletteDialog onClose={onClose} /> : null;
}

/** Hits for one trimmed query; hits for any other query are stale and never shown or followed. */
type Results = { query: string; hits: SearchHit[]; error: string | null };

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const { client, labId } = useClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Results | null>(null);
  const [active, setActive] = useState(0);
  // The trimmed query Enter was pressed for before its results arrived.
  const [pendingEnter, setPendingEnter] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const titleId = useId();

  const q = query.trim();
  const current = results !== null && results.query === q ? results : null;
  const hits = current?.hits ?? null;

  // Remember what had focus when the palette opened, and hand focus back when it closes. If that
  // element has gone or is hidden, focus goes to the sidebar's Search button.
  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    input.current?.focus();
    return () => {
      if (trigger && trigger.isConnected && trigger.checkVisibility()) trigger.focus();
      else document.querySelector<HTMLElement>("[data-palette-trigger]")?.focus();
    };
  }, []);

  useEffect(() => {
    if (q === "") return;
    let live = true;
    const timer = window.setTimeout(() => {
      client.search(labId, q).then(
        (found) => { if (live) { setResults({ query: q, hits: found, error: null }); setActive(0); } },
        (e: unknown) => {
          if (live) setResults({ query: q, hits: [], error: e instanceof Error ? e.message : String(e) });
        },
      );
    }, DEBOUNCE_MS);
    return () => { live = false; window.clearTimeout(timer); };
  }, [client, labId, q]);

  // Changing the hash closes the palette through the hashchange listener below, after the new
  // route has rendered, so focus can be returned to whatever is still on screen.
  const choose = (hit: SearchHit) => {
    if (window.location.hash === hit.href) onClose();
    else window.location.hash = hit.href;
  };

  // Enter pressed before the results arrived: follow the first hit once they do, or do nothing.
  useEffect(() => {
    if (pendingEnter === null || current === null) return;
    setPendingEnter(null);
    if (pendingEnter === current.query && current.hits.length > 0) choose(current.hits[0]);
  });

  // A route change from anywhere closes the palette.
  useEffect(() => {
    window.addEventListener("hashchange", onClose);
    return () => window.removeEventListener("hashchange", onClose);
  }, [onClose]);

  // Escape and Tab are handled on the document, so they work wherever focus is while it's open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab") {
        // The input is the only focus stop, so Tab keeps focus inside the dialog.
        e.preventDefault();
        input.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const optionId = (i: number) => `${listId}-option-${i}`;
  const showList = hits !== null && hits.length > 0;

  useEffect(() => {
    if (!showList) return;
    document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
  });

  const onKeyDown = (e: ReactKeyboardEvent) => {
    const count = hits?.length ?? 0;
    if (e.key === "ArrowDown" && count > 0) {
      e.preventDefault();
      setActive((i) => (i + 1) % count);
    } else if (e.key === "ArrowUp" && count > 0) {
      e.preventDefault();
      setActive((i) => (i - 1 + count) % count);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (hits && hits[active]) choose(hits[active]);
      else if (hits === null && q !== "") setPendingEnter(q);
    }
  };

  let note: string | null = null;
  if (q === "") note = "Find projects, experiments, documents, instruments, skills and connectors.";
  else if (current?.error) note = `Search failed: ${current.error}`;
  else if (hits !== null && hits.length === 0) note = "No matches";
  else if (hits === null) note = "Searching";

  return (
    <div className="palette-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        onMouseDown={(e) => {
          // Clicking anywhere but the input keeps focus in the input.
          if (e.target !== input.current) e.preventDefault();
        }}
      >
        <h2 id={titleId} className="visually-hidden">Search</h2>
        <div className="palette-field">
          <Search size={18} aria-hidden="true" />
          <input
            ref={input}
            type="text"
            role="combobox"
            aria-label="Search the lab"
            aria-expanded={showList}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={showList ? optionId(active) : undefined}
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className="palette-results" hidden={!showList}>
          {showList && hits.map((hit, i) => (
            <li
              key={`${hit.kind}:${hit.id}:${hit.href}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className="palette-option"
              onMouseMove={() => setActive(i)}
              onClick={() => choose(hit)}
            >
              <span className="palette-title">{hit.title}</span>
              <span className="palette-kind">{KIND_LABEL[hit.kind]}</span>
            </li>
          ))}
        </ul>
        {note && <p className="palette-note" role="status">{note}</p>}
      </div>
    </div>
  );
}
