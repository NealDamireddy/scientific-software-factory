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

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const { client, labId } = useClient();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const listId = useId();
  const titleId = useId();

  // Remember what had focus when the palette opened, and hand focus back when it closes.
  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    input.current?.focus();
    return () => {
      if (trigger && trigger.isConnected) trigger.focus();
    };
  }, []);

  useEffect(() => {
    const request = ++latest.current;
    const q = query.trim();
    if (q === "") {
      setHits(null);
      setSearching(false);
      setError(null);
      return;
    }
    setSearching(true);
    const timer = window.setTimeout(() => {
      client.search(labId, q).then(
        (found) => {
          if (request !== latest.current) return; // a newer query has been typed
          setHits(found);
          setActive(0);
          setError(null);
          setSearching(false);
        },
        (e: unknown) => {
          if (request !== latest.current) return;
          setHits([]);
          setError(e instanceof Error ? e.message : String(e));
          setSearching(false);
        },
      );
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [client, labId, query]);

  const choose = (hit: SearchHit) => {
    onClose();
    window.location.hash = hit.href;
  };

  const onKeyDown = (e: ReactKeyboardEvent) => {
    const count = hits?.length ?? 0;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "Tab") {
      // The input is the only focus stop, so Tab keeps focus inside the dialog.
      e.preventDefault();
      input.current?.focus();
    } else if (e.key === "ArrowDown" && count > 0) {
      e.preventDefault();
      setActive((i) => (i + 1) % count);
    } else if (e.key === "ArrowUp" && count > 0) {
      e.preventDefault();
      setActive((i) => (i - 1 + count) % count);
    } else if (e.key === "Enter" && hits && hits[active]) {
      e.preventDefault();
      choose(hits[active]);
    }
  };

  const optionId = (i: number) => `${listId}-option-${i}`;
  const showList = hits !== null && hits.length > 0;
  let note: string | null = null;
  if (query.trim() === "") note = "Find projects, experiments, documents, instruments, skills and connectors.";
  else if (error) note = `Search failed: ${error}`;
  else if (hits !== null && hits.length === 0 && !searching) note = "No matches";
  else if (hits === null) note = "Searching";

  return (
    <div className="palette-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
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
              onMouseDown={(e) => e.preventDefault()}
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
