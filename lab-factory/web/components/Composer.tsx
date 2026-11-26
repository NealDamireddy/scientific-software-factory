"use client";

import { ArrowUp, Paperclip, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { errorText } from "../lib/status.ts";

type Draft = { text: string; files: File[] };
type FailedSend = { id: number; draft: Draft; error: string };
type Editor = { draft: Draft; error: string | null; failed: FailedSend[] };

/**
 * The message box under the conversation: text, attached files as removable chips, and Send.
 * Enter sends and Shift+Enter starts a new line. While the factory works, sending waits.
 */
export function Composer({ busy, onSend }: {
  /** A send or a build is in flight. */
  busy: boolean;
  /** Sends the message. A rejected send can be retried with its original files. */
  onSend: (text: string, files: File[]) => Promise<void>;
}) {
  const [editor, setEditor] = useState<Editor>({ draft: { text: "", files: [] }, error: null, failed: [] });
  const { draft: { text, files }, error } = editor;
  const attempt = useRef(0);
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

  function editDraft(update: (draft: Draft) => Draft) {
    setEditor((current) => ({ ...current, error: null, draft: update(current.draft) }));
  }

  function discardFailure(id: number) {
    setEditor((current) => ({ ...current, failed: current.failed.filter((item) => item.id !== id) }));
  }

  async function send(retry?: FailedSend) {
    if (inFlight.current || busy || (!retry && empty)) return;
    inFlight.current = true;
    const sent = retry?.draft ?? editor.draft;
    const id = retry?.id ?? ++attempt.current;
    const cleared = { text: "", files: [] };
    if (!retry) setEditor((current) => ({ ...current, draft: cleared, error: null }));
    try {
      await onSend(sent.text, sent.files);
      if (retry) discardFailure(id);
    } catch (e) {
      const error = errorText(e);
      setEditor((current) => {
        // Restore an untouched editor. Any intervening edit creates a different draft.
        if (!retry && current.draft === cleared) return { ...current, draft: sent, error };
        const failed = current.failed.filter((item) => item.id !== id);
        return { ...current, failed: [...failed, { id, draft: sent, error }] };
      });
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
    editDraft((draft) => ({ ...draft, files: [...draft.files, ...added] }));
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
          onChange={(e) => {
            const value = e.currentTarget.value;
            editDraft((draft) => ({ ...draft, text: value }));
          }}
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
                    editDraft((draft) => ({ ...draft, files: draft.files.filter((_, i) => i !== index) }));
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
      {editor.failed.map((failed) => (
        <div className="ws-error" key={failed.id}>
          <p role="alert">Couldn’t send {failed.draft.text || failed.draft.files.map((file) => file.name).join(", ")}. {failed.error}</p>
          <button type="button" className="ws-button" disabled={busy} onClick={() => void send(failed)}>Retry message</button>
          <button type="button" className="ws-button" disabled={busy} onClick={() => discardFailure(failed.id)}>Dismiss</button>
        </div>
      ))}
    </form>
  );
}
