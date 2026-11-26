// Runs Python in one module worker (public/runtime/python-worker.mjs) on the self-hosted Pyodide.
//
// Protocol. The runner posts { id, code, entry, args }. The worker answers with
//   { id, ok: true, value }        the entry's return value, converted to plain JS
//   { id, ok: false, error }       a Python exception; error is str(e)
//   { id, ok: false, load_error }  Pyodide itself failed to load; load_error is the reason
// The worker calls entry(**args) when args is an object, so callers pass keyword arguments:
// run(code, "analyze", { readings }) and run(code, "simulate", {}).

export const RUNTIME_TIMEOUT_MESSAGE = "The analysis runtime didn't respond within 60 s. Reload the page and try again.";

export function runtimeLoadMessage(reason: string): string {
  return `The analysis runtime couldn't load: ${reason}`;
}

export type PythonRunner = {
  run(code: string, entry: string, args: unknown): Promise<unknown>;
  dispose(): void;
};

type Reply = { id: number; ok: boolean; value?: unknown; error?: string; load_error?: string };
type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> };

export function createPythonRunner(options: { workerUrl?: string; timeoutMs?: number } = {}): PythonRunner {
  const workerUrl = options.workerUrl ?? "/runtime/python-worker.mjs";
  const timeoutMs = options.timeoutMs ?? 60_000;
  const pending = new Map<number, Pending>();
  let worker: Worker | null = null;
  let nextId = 1;

  function settle(id: number): Pending | undefined {
    const entry = pending.get(id);
    if (entry) {
      clearTimeout(entry.timer);
      pending.delete(id);
    }
    return entry;
  }

  // Ends the current worker and rejects everything it was running; the next run starts a fresh one.
  function fail(error: Error): void {
    worker?.terminate();
    worker = null;
    for (const id of [...pending.keys()]) settle(id)?.reject(error);
  }

  function onMessage(event: MessageEvent<Reply>): void {
    const reply = event.data;
    if (reply.load_error !== undefined) {
      fail(new Error(runtimeLoadMessage(reply.load_error)));
      return;
    }
    const entry = settle(reply.id);
    if (!entry) return;
    if (reply.ok) entry.resolve(reply.value);
    else entry.reject(new Error(reply.error || "The analysis failed."));
  }

  function onError(event: Event): void {
    event.preventDefault?.();
    const message = (event as ErrorEvent).message;
    fail(new Error(runtimeLoadMessage(message || `the worker at ${workerUrl} didn't start`)));
  }

  function current(): Worker {
    if (!worker) {
      const created = new globalThis.Worker(workerUrl, { type: "module" });
      created.addEventListener("message", onMessage);
      created.addEventListener("error", onError);
      worker = created;
    }
    return worker;
  }

  return {
    run(code, entry, args) {
      return new Promise((resolve, reject) => {
        let target: Worker;
        try {
          target = current();
        } catch (error) {
          reject(new Error(runtimeLoadMessage(error instanceof Error ? error.message : String(error))));
          return;
        }
        const id = nextId;
        nextId += 1;
        const timer = setTimeout(() => {
          if (pending.has(id)) fail(new Error(RUNTIME_TIMEOUT_MESSAGE));
        }, timeoutMs);
        pending.set(id, { resolve, reject, timer });
        try {
          target.postMessage({ id, code, entry, args });
        } catch (error) {
          settle(id)?.reject(error instanceof Error ? error : new Error(String(error)));
        }
      });
    },
    dispose() {
      fail(new Error("The analysis runtime was closed."));
    },
  };
}
