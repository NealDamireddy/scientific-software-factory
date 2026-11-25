import {loadPyodide} from "/runtime/pyodide.mjs";

self.onmessage = async ({data}) => {
  try {
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(data.source));
    const digest = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
    if (digest !== data.expected) throw Error("The submitted application and acquired run have different source digests.");
    const python = await loadPyodide({indexURL:"/runtime/"});
    python.globals.set("source", data.source);
    async function analyze(input) {
      python.globals.set("payload", JSON.stringify(input));
      const output = await python.runPythonAsync(`
import contextlib, io, sys
sys.stdin = io.StringIO(payload)
with contextlib.redirect_stdout(io.StringIO()) as report:
    exec(compile(source, "analysis.py", "exec"), {"__name__": "__main__"})
report.getvalue()
`);
      return JSON.parse(output);
    }
    const output = await analyze(data.input);
    const paperOutput = data.paperInput ? await analyze(data.paperInput) : undefined;
    self.postMessage({output, paperOutput, python:python.runPython("sys.version.split()[0]")});
  } catch (error) {
    self.postMessage({error:String(error.message || error)});
  }
};
