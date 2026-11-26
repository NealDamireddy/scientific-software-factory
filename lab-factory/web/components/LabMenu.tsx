"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { Lab, Role } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import type { Theme } from "./ClientContext.tsx";

const ROLES: [Role, string][] = [["researcher", "Researcher"], ["approver", "Approver"]];
const THEMES: [Theme, string][] = [["system", "System"], ["light", "Light"], ["dark", "Dark"]];

function attentionLabel(n: number): string {
  return n === 1 ? "1 item needs your attention" : `${n} items need your attention`;
}

/** The lab switcher at the top of the sidebar and the popover it opens. */
export function LabMenu() {
  const { client, mode, labId, role, setRole, theme, setTheme, version, resetSample } = useClient();
  const [, navigate] = useRoute();
  const [lab, setLab] = useState<Lab | null>(null);
  const [attention, setAttention] = useState(0);
  const [open, setOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const switcher = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useEffect(() => {
    let live = true;
    client.getLab(labId).then((l) => { if (live) setLab(l); }, () => undefined);
    return () => { live = false; };
  }, [client, labId, version]);

  useEffect(() => {
    let live = true;
    client.needsAttention(labId, role).then((items) => { if (live) setAttention(items.length); }, () => undefined);
    return () => { live = false; };
  }, [client, labId, role, version]);

  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) switcher.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    // Focus the checked choice of the first group.
    const first = popover.current?.querySelector(".menu-group");
    (first?.querySelector<HTMLElement>("input:checked") ?? first?.querySelector<HTMLElement>("input"))?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close(true);
      }
    };
    const onPointer = (e: PointerEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const reset = async () => {
    if (mode !== "sample" || resetting) return;
    setResetting(true);
    try {
      await resetSample();
      navigate({ view: "home" });
      close(true);
    } finally {
      setResetting(false);
    }
  };

  return (
    <div
      className="lab-menu"
      ref={wrapper}
      onBlur={(e) => {
        // Tabbing out of the popover closes it.
        if (open && !wrapper.current?.contains(e.relatedTarget as Node | null) && e.relatedTarget) close(false);
      }}
    >
      <button
        type="button"
        ref={switcher}
        className="lab-switcher"
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="lab-switcher-name">{lab?.name ?? "Lab"}</span>
        {attention > 0 && (
          <span className="attention-badge">
            <span aria-hidden="true">{attention}</span>
            <span className="visually-hidden">, {attentionLabel(attention)}</span>
          </span>
        )}
        <ChevronDown size={16} aria-hidden="true" />
      </button>

      <div id={popoverId} ref={popover} className="lab-popover" hidden={!open}>
        <fieldset className="menu-group">
          <legend>Viewing as</legend>
          {ROLES.map(([value, label]) => (
            <label key={value} className="menu-choice">
              <input type="radio" name="labfactory-role" value={value} checked={role === value}
                onChange={() => setRole(value)} />
              {label}
            </label>
          ))}
        </fieldset>
        <fieldset className="menu-group">
          <legend>Theme</legend>
          {THEMES.map(([value, label]) => (
            <label key={value} className="menu-choice">
              <input type="radio" name="labfactory-theme" value={value} checked={theme === value}
                onChange={() => setTheme(value)} />
              {label}
            </label>
          ))}
        </fieldset>
        <div className="menu-group">
          <a className="menu-item" href={routeHref({ view: "settings" })} onClick={() => close(false)}>Lab settings</a>
          {mode === "sample" && (
            <button type="button" className="menu-item" onClick={reset} disabled={resetting}>
              Reset sample data
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
