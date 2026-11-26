"use client";

import { ArrowUp, Paperclip, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { errorText } from "../lib/status.ts";

/**
 * The message box under the conversation: text, attached files as removable chips, and Send.
 * Enter sends and Shift+Enter starts a new line. While the factory works, sending waits.
 */
export function Composer({ busy, onSend }: {
  /** A send or a build is in flight. */
  busy: boolean;
  /** Sends the message. Rejects with the client's error, and the draft is put back. */
  onSend: (text: string, files: File[]) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const fieldId = useId();
  const attachInput = useRef<HTMLInputElement>(null);
  const chips = useRef<HTMLUListElement>(null);
  // After a chip is removed, focus goes to the next chip, or to the attach control when none remain.
  const focusAfterRemove = useRef<number | null>(null);

  useEffect(() => {
    const index = focusAfterRemove.current;
    if (index === null) return;
    focusAfterRemove.current = null;
    const buttons = chips.current?.querySelectorAll<HTMLButtonElement>(".ws-chip-remove");
    if (buttons && buttons.length > 0) buttons[Math.min(index, buttons.length - 1)].focus();
    else attachInput.current?.focus();
  }, [files]);

  const empty = text.trim() === "" && files.length === 0;
  const disabled = empty || busy;

  async function send() {
    if (inFlight.current || busy || empty) return;
    inFlight.current = true;
    const draft = { text, files };
    setError(null);
    setText("");
    setFiles([]);
    try {
      await onSend(draft.text, draft.files);
    } catch (e) {
      setText(draft.text);
      setFiles(draft.files);
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // Enter that confirms an input method's composition is not a send.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    void send();
  }

  function addFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    const added = Array.from(list);
    setFiles((current) => [...current, ...added]);
  }

  return (
    <form className="ws-composer" onSubmit={onSubmit}>
      <div className="ws-composer-box">
        <label htmlFor={fieldId} className="visually-hidden">Message the factory</label>
        <textarea
          id={fieldId}
          className="ws-composer-input"
          rows={2}
          placeholder="Ask a question or attach a protocol"
          value={text}
          onChange={(e) => setText(e.currentTarget.value)}
          onKeyDown={onKeyDown}
        />
        {files.length > 0 ? (
          <ul ref={chips} className="ws-chips" aria-label="Attached files">
            {files.map((file, index) => (
              <li key={`${index}-${file.name}`} className="ws-chip">
                <span className="ws-chip-name">{file.name}</span>
                <button
                  type="button"
                  className="ws-chip-remove"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => {
                    focusAfterRemove.current = index;
                    setFiles((current) => current.filter((_, i) => i !== index));
                  }}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="ws-composer-actions">
          <label className="ws-attach" title="Attach files">
            <input
              ref={attachInput}
              type="file"
              multiple
              className="visually-hidden"
              onChange={(e) => {
                addFiles(e.currentTarget.files);
                // Cleared so the same file can be chosen again after removing it.
                e.currentTarget.value = "";
              }}
            />
            <Paperclip size={18} aria-hidden="true" />
            <span className="visually-hidden">Attach files</span>
          </label>
          <p className="ws-working" role="status">{busy ? "The factory is working…" : ""}</p>
          <button type="submit" className="ws-send" disabled={disabled}>
            <ArrowUp size={18} aria-hidden="true" />
            <span>Send</span>
          </button>
        </div>
      </div>
      {error ? <p className="ws-error" role="alert">{error}</p> : null}
    </form>
  );
}
