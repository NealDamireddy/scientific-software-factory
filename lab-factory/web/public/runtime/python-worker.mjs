// Runs Python for the page, on the Pyodide files served from /runtime/ (copied from
// node_modules by scripts/copy-runtime.mjs). Nothing is fetched from anywhere else, and
// no packages are installed: the code may use the standard library only.
//
// Request:  { id, code, entry, args }
// Replies:  { id, ok: true, value }        the entry's return value as plain JS
//           { id, ok: false, error }       a Python exception, as str(e)
//           { id, ok: false, load_error }  Pyodide failed to load, with the reason
// The code runs in a fresh namespace each time. The entry is called as entry(**args) when
// args is an object, otherwise as entry(args).
import { loadPyodide } from "/runtime/pyodide.mjs";

const RUN = `
def _run(code, entry, args):
    try:
        namespace = {"__name__": "__lab_factory__"}
        exec(code, namespace)
        if not callable(namespace.get(entry)):
            raise ValueError(f"The code has no function named {entry}.")
        function = namespace[entry]
        value = function(**args) if isinstance(args, dict) else function(args)
        return {"ok": True, "value": value}
    except BaseException as e:
        return {"ok": False, "error": str(e) or type(e).__name__}

_run
`;

function reason(error) {
  if (error instanceof Error && error.message) return error.message;
  if (error && typeof error === "object" && typeof error.message === "string" && error.message) return error.message;
  const text = String(error);
  // Some download failures reject with a bare event or response, which has nothing to say.
  return text === "" || text === "[object Object]" || text.startsWith("[object ") ? "a runtime file didn't download" : text;
}

const ready = loadPyodide({ indexURL: "/runtime/" }).then((pyodide) => ({
  pyodide,
  run: pyodide.runPython(RUN, { globals: pyodide.toPy({}) }),
}));
// Failures are reported per request below; this keeps them from also surfacing as unhandled.
ready.catch(() => {});

self.addEventListener("message", async (event) => {
  const { id, code, entry, args } = event.data ?? {};
  let runtime;
  try {
    runtime = await ready;
  } catch (error) {
    self.postMessage({ id, ok: false, load_error: reason(error) });
    return;
  }
  const { pyodide, run } = runtime;
  const pyArgs = pyodide.toPy(args ?? null);
  let result;
  try {
    result = run(code, entry, pyArgs);
    const reply = result.toJs({ dict_converter: Object.fromEntries, create_pyproxies: false });
    self.postMessage(reply.ok ? { id, ok: true, value: reply.value } : { id, ok: false, error: reply.error });
  } catch (error) {
    self.postMessage({ id, ok: false, error: `The result couldn't be returned: ${reason(error)}` });
  } finally {
    result?.destroy?.();
    pyArgs?.destroy?.();
  }
});
