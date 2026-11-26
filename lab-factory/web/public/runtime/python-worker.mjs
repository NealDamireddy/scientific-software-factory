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
//
// Analysis code sees readings that must stay in the browser. Once Pyodide has loaded (it needs no
// network after that), the worker takes away every way it has to make a request, before any of
// that code runs: Python's `js` module is this worker's global, so it sees the same refusals.
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

const NO_NETWORK = "Network access is not available to analysis code.";
// Each can send a request, or start a context (a nested worker) that could.
const NETWORK_NAMES = [
  "fetch", "XMLHttpRequest", "WebSocket", "WebSocketStream", "EventSource", "WebTransport", "importScripts",
  "Worker", "SharedWorker", "caches", "sendBeacon",
];

function refuse() {
  throw new Error(NO_NETWORK);
}

/** Replaces each network capability on an object and on everything it inherits from, for good. */
function disarm(target) {
  for (let object = target; object && object !== Object.prototype; object = Object.getPrototypeOf(object)) {
    for (const name of NETWORK_NAMES) {
      if (!Object.prototype.hasOwnProperty.call(object, name)) continue;
      Object.defineProperty(object, name, { value: refuse, writable: false, configurable: false, enumerable: false });
    }
  }
  // The global itself gets the refusal too, even where the name was never defined, so a lookup can't
  // fall through to anything restored later.
  for (const name of NETWORK_NAMES) {
    const own = Object.getOwnPropertyDescriptor(target, name);
    if (!own || own.configurable || own.value !== refuse) {
      try {
        Object.defineProperty(target, name, { value: refuse, writable: false, configurable: false, enumerable: false });
      } catch {
        // A property the platform won't let go of stays as the loop above left it.
      }
    }
  }
}

function lock(object, name, value) {
  Object.defineProperty(object, name, { value, writable: false, configurable: false, enumerable: false });
}

// Running a string as code would reach dynamic import(), which requests a module from any URL.
function removeCodeFromStrings() {
  lock(self, "eval", refuse);
  const refusing = { apply: refuse, construct: refuse };
  const constructors = [
    Function,
    Object.getPrototypeOf(async function () {}).constructor,
    Object.getPrototypeOf(function* () {}).constructor,
    Object.getPrototypeOf(async function* () {}).constructor,
  ];
  for (const make of constructors) {
    // A proxy keeps `instanceof Function` working while refusing to build code.
    const proxy = new Proxy(make, refusing);
    lock(make.prototype, "constructor", proxy);
    if (self[make.name] === make) lock(self, make.name, proxy);
  }
  // Timers run a string handler as code; only functions are accepted.
  for (const name of ["setTimeout", "setInterval"]) {
    const original = self[name];
    const guarded = function (handler, ...rest) {
      if (typeof handler !== "function") refuse();
      return original.call(self, handler, ...rest);
    };
    for (let object = Object.getPrototypeOf(self); object && object !== Object.prototype; object = Object.getPrototypeOf(object)) {
      if (Object.prototype.hasOwnProperty.call(object, name)) lock(object, name, guarded);
    }
    lock(self, name, guarded);
  }
}

function removeNetworkAccess() {
  disarm(self);
  if (self.navigator) disarm(self.navigator);
  removeCodeFromStrings();
}

const ready = loadPyodide({ indexURL: "/runtime/" }).then((pyodide) => {
  removeNetworkAccess();
  return { pyodide, run: pyodide.runPython(RUN, { globals: pyodide.toPy({}) }) };
});
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
