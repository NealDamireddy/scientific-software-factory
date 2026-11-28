"use client";

import { useEffect, useRef } from "react";
import { mountReviewer } from "../../lab-factory/public/app.js";
import { buildAgentContext, type ExtensionState } from "./extension-model";
import reviewerDocument from "../../lab-factory/public/index.html?reviewer-template";

export const labViews: Record<string, string> = {
  orders: "Work orders", order: "Submission review", references: "Reference library",
  analysis: "Tabular analysis", context: "Lab context", agents: "Agent access",
  b12: "B12 analysis", honey: "Honey moisture",
};

export function LabOperations({ route, extensions, sessionChanged }: { route: string; extensions: ExtensionState; sessionChanged: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const onSession = useRef(sessionChanged);
  onSession.current = sessionChanged;
  useEffect(() => {
    if (!host.current) return;
    const root = host.current.shadowRoot || host.current.attachShadow({mode: "open"});
    // Import only the source-controlled form/template markup. The shared module owns all behavior.
    const template = new DOMParser().parseFromString(reviewerDocument, "text/html");
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "/style.css";
    root.replaceChildren(stylesheet, ...Array.from(template.body.querySelectorAll(":scope > :not(script)"), node => document.importNode(node, true)));
    const controller = new AbortController();
    const skills = buildAgentContext(extensions).skills.map(({id, name, whenToUse, instructions, stage}) =>
      ({id, name, whenToUse, instructions, ...(stage ? {stage} : {})}));
    mountReviewer(root, controller.signal, () => onSession.current(), skills);
    return () => { controller.abort(); root.replaceChildren(); };
  }, [route, extensions]);
  return <div ref={host} />;
}
