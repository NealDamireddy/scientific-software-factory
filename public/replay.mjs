import {loadPyodide} from "/runtime/pyodide.mjs";

async function verifiedFile(folder, name, manifest) {
  const response = await fetch(folder + "/" + name);
  if (!response.ok) throw Error("Unable to read " + name);
  const bytes = await response.arrayBuffer();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), n=>n.toString(16).padStart(2,"0")).join("");
  if (digest !== manifest[name].sha256) throw Error(name + " failed its integrity check");
  return new TextDecoder().decode(bytes);
}

self.onmessage = async ({data}) => {
  try {
    const {folder,manifest,reference} = data;
    const [source,raw,metadata] = await Promise.all(["analysis.py","input.csv","metadata.json"].map(name=>verifiedFile(folder,name,manifest)));
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
    const output = JSON.parse(response);
    const passed = reference.metrics.every(({field,expected,tolerance})=>{
      const actual = output[field];
      const within = (a,b)=>typeof a === "number" && Number.isFinite(a) && Math.abs(a-b)<=tolerance;
      return Array.isArray(expected) ? Array.isArray(actual) && actual.length===expected.length && expected.every((n,i)=>within(actual[i],n)) : within(actual,expected);
    });
    self.postMessage({passed,output,python:python.runPython("sys.version.split()[0]")});
  } catch (error) {self.postMessage({error:String(error.message || error)});}
};
