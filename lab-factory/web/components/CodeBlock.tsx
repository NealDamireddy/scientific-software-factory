"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { tokenizePython } from "../lib/python-tokens.ts";

const COPIED_MS = 2000;

/**
 * Python source in a focusable scroll region named by `label`, with `Copy code`. Keywords are tinted
 * indigo, strings and comments steel; long lines scroll inside the block.
 */
export function CodeBlock({ code, label }: { code: string; label: string }) {
  const uid = useId();
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tokens = useMemo(() => tokenizePython(code), [code]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(code);
      setFailed(false);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      setCopied(false);
      setFailed(true);
    }
  }

  return (
    <div className="code-block">
      <div className="code-head">
        <span id={`${uid}-label`} className="code-label">{label}</span>
        <span className="code-actions">
          <span role="status" className="code-status">{copied ? "Copied" : ""}</span>
          <button type="button" className="ws-button code-copy" onClick={copy}>Copy code</button>
        </span>
      </div>
      <pre className="code-pre" role="region" tabIndex={0} aria-labelledby={`${uid}-label`}>
        <code>
          {tokens.map((t, i) => (t.kind === "text" ? t.text : <span key={i} className={`code-${t.kind}`}>{t.text}</span>))}
        </code>
      </pre>
      {failed && <p role="alert" className="pg-error code-error">Couldn&apos;t copy. Select the text and copy it yourself.</p>}
    </div>
  );
}
