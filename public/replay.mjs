import {loadPyodide} from "/runtime/pyodide.mjs";
import {checkManifest,checkSourceRevision,metricsPass,sha256Hex} from "/replay-checks.mjs";

async function verifiedFile(folder, name, manifest, sourceRevision) {
  const response = await fetch(folder + "/" + name);
  if (!response.ok) throw Error("Unable to read " + name);
  const bytes = await response.arrayBuffer();
  const digest = await sha256Hex(bytes);
  checkManifest(name, digest, manifest);
  if (name === "analysis.py") checkSourceRevision(digest, sourceRevision);
  return new TextDecoder().decode(bytes);
}

self.onmessage = async ({data}) => {
  try {
    const {folder,manifest,reference,sourceRevision} = data;
    if (!reference?.metrics?.length) throw Error("The reference case has no metrics to compare, so replay cannot pass");
    const [source,raw,metadata] = await Promise.all(["analysis.py","input.csv","metadata.json"].map(name=>verifiedFile(folder,name,manifest,sourceRevision)));
    const python = await loadPyodide({indexURL:"/runtime/"});
    python.globals.set("app_source",source);
    python.globals.set("csv_data",raw);
    python.globals.set("meta_json",metadata);
    const response = await python.runPythonAsync(`
import io,sys,contextlib
sys.argv = ["analysis.py",meta_json]
sys.stdin = io.StringIO(csv_data)
output = io.StringIO()
with contextlib.redirect_stdout(output):
    try:
        exec(compile(app_source, "analysis.py", "exec"), {"__name__": "__main__"})
    except SystemExit as ex:
        if ex.code not in (None, 0):
            raise ValueError("Application exited with " + str(ex.code) + " " + output.getvalue())
output.getvalue()
`);
    let output;
    try { output = JSON.parse(response); } catch { throw Error("analysis.py did not print valid JSON (NaN and Infinity are not allowed)"); }
    self.postMessage({passed:metricsPass(reference,output),output,python:python.runPython("sys.version.split()[0]")});
  } catch (error) {self.postMessage({error:String(error.message || error)});}
};
