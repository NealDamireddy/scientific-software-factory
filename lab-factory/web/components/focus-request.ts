// Asks a form field elsewhere on the page to take focus: the sidebar's `New project` and
// `New experiment` lead to a form, which may already be on screen (the hash then doesn't change).
// The request waits until a field that answers to it is mounted, then is used once.
import { useEffect } from "react";
import type { RefObject } from "react";

export type FocusTarget = "project-title" | "experiment-description";

let pending: FocusTarget | null = null;
const listeners = new Set<() => void>();

export function requestFocus(target: FocusTarget): void {
  pending = target;
  for (const listener of listeners) listener();
}

/** Focuses the field, and scrolls it into view, whenever a request names `target`. */
export function useFocusRequest(target: FocusTarget, ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    function take() {
      const field = ref.current;
      if (pending !== target || !field) return;
      pending = null;
      field.scrollIntoView({ block: "center" });
      field.focus({ preventScroll: true });
    }
    listeners.add(take);
    take();
    return () => { listeners.delete(take); };
  }, [target, ref]);
}
