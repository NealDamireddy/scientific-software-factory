"use client";

import "./pages.css";
import "./extensions.css";

import { useEffect, useId, useRef, useState } from "react";

export type CopyFieldProps = {
  label: string;
  value: string;
  language?: "shell" | "toml" | "json" | "markdown";
};

const COPIED_MS = 2000;

/** A labelled block of text to copy. Long lines scroll inside the block. */
export function CopyField({ label, value, language }: CopyFieldProps) {
  const uid = useId();
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(value);
      setFailed(false);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      setCopied(false);
      setFailed(true);
    }
  }

  return (
    <div className="copy-field">
      <div className="copy-head">
        <span id={`${uid}-label`} className="copy-label">{label}</span>
        <span className="copy-actions">
          <span role="status" className="copy-status">{copied ? "Copied" : ""}</span>
          <button type="button" className="pg-button pg-quiet" aria-label={`Copy ${label}`} onClick={copy}>
            Copy
          </button>
        </span>
      </div>
      <pre className="copy-pre" role="region" tabIndex={0} aria-labelledby={`${uid}-label`} data-language={language}>
        <code>{value}</code>
      </pre>
      {failed && (
        <p role="alert" className="pg-error copy-error">Couldn&apos;t copy. Select the text and copy it yourself.</p>
      )}
    </div>
  );
}
