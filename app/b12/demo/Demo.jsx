"use client";
import {useEffect, useRef, useState} from "react";
import {Download, Play} from "lucide-react";


function downloadEvidence(record) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], {type:"application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "b12-" + record.acquisition.run_id + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function presenterRequest(action, body) {
  const response = await fetch("/api/presenter/" + action, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "Presenter request failed.");
  return result;
}

export default function Demo({savedRelease, paper, preset}) {
  const [local, setLocal] = useState(null);
  const [spec, setSpec] = useState("");
  const [generated, setGenerated] = useState(null);
  const release = local ? generated : savedRelease;
  const [phase,setPhase] = useState("");
  const [acquisition,setAcquisition] = useState(null);
  const [report,setReport] = useState(null);
  const [error,setError] = useState("");
  const inFlight = useRef(false);
  const worker = useRef(null);
  const controller = useRef(null);
  const source = release?.files["analysis.py"];
  useEffect(() => {
    setLocal(window.location.origin === "http://127.0.0.1:8776");
  }, []);

  function editSpec(value) {
    setSpec(value);
    setGenerated(null);
    reset();
  }
  async function generate() {
    if (inFlight.current) return;
    inFlight.current = true;
    setGenerated(null);
    reset();
    setPhase("Generating Python and the instrument recipe, then checking the app…");
    try {
      let parsed;
      try { parsed = JSON.parse(spec); }
      catch { throw Error("Enter valid JSON or click Insert experiment specs to restore the preset."); }
      setGenerated(await presenterRequest("generate", parsed));
    } catch (cause) {
      setError(cause.message);
    } finally {
      inFlight.current = false;
      setPhase("");
    }
  }

  useEffect(() => () => {
    controller.current?.abort();
    worker.current?.terminate();
  }, []);
  function reset() {
    setAcquisition(null);
    setReport(null);
    setError("");
  }
  async function run() {
    if (inFlight.current) return;
    inFlight.current = true;
    reset();
    setPhase("Acquiring three detector readings…");
    const abort = new AbortController();
    controller.current = abort;
    const timer = setTimeout(() => abort.abort(), 45000);
    let analysisTimer;
    try {
      if (local) {
        const {acquisition, analysis} = await presenterRequest("run", generated.id);
        if (acquisition.revision !== release.revision) throw Error("The acquisition revision differs from the generated app.");
        setAcquisition(acquisition);
        setReport(analysis);
        return;
      }
      const response = await fetch("/api/instrument", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...release, vial: "A"}), signal:abort.signal
      });
      if (!response.ok) throw Error("Instrument request failed (HTTP " + response.status + ").");
      const receipt = await response.json();
      if (receipt.revision !== release.revision) throw Error("The instrument returned a different application revision.");
      setAcquisition(receipt);
      setPhase("Running the submitted Python application…");
      const thread = new Worker("/b12/analyze.mjs", {type:"module"});
      worker.current = thread;
      const analysis = await new Promise((resolve,reject) => {
        analysisTimer = setTimeout(() => reject(Error("Analysis timed out. Submit again to start a fresh run.")), 60000);
        thread.onmessage = ({data}) => data.error ? reject(Error(data.error)) : resolve(data);
        thread.onerror = () => reject(Error("The Python analysis worker could not start."));
        thread.postMessage({
          source, expected: receipt.source_sha256, input: receipt.analysis_input,
          paperInput: {
            sample_id: paper.sample.id, preparation: null, calibration: receipt.analysis_input.calibration,
            absorbances: [paper.sample.mean_absorbance],
          },
        });
      });
      setReport(analysis);
    } catch (cause) {
      setError(cause.name === "AbortError" ? "Instrument request timed out." : cause.message);
    } finally {
      clearTimeout(timer);
      clearTimeout(analysisTimer);
      worker.current?.terminate();
      worker.current = null;
      controller.current = null;
      setPhase("");
      inFlight.current = false;
    }
  }
  const result = report?.output;
  const paperEstimate = report?.paperOutput?.concentration_mg_l;
  const difference = paperEstimate == null ? null : paperEstimate - paper.sample.prepared_ppm;
  return <><section className="workspace-card assay-run" aria-labelledby="app-title">
    <h2 id="app-title">{local ? "Build the analysis application" : "Analysis application"}</h2>
    {local && <>
      <button disabled={!!phase} onClick={() => editSpec(JSON.stringify(preset, null, 2))}>Insert experiment specs</button>
      {spec && <div className="assay-brief">
        <label>Application specification<textarea value={spec} disabled={!!phase} spellCheck={false} onChange={e => editSpec(e.target.value)}/></label>
        <p>You can edit the application name. The measurement settings match the simulator protocol above.</p>
        <button disabled={!!phase} onClick={generate}>Generate analysis app</button>
      </div>}
      {generated && <p className="build-receipt"><strong>{JSON.parse(generated.files["views.json"]).title}</strong> · Generated by {generated.worker.model} · {generated.checks.length} checks passed</p>}
    </>}
    {local === false && <p>This hosted demo runs the previously generated B12 app. Live generation is available in the local presenter.</p>}
    {release && local !== null && <details><summary>Inspect generated files</summary>
      <h3>Instrument recipe</h3><pre>{release.files["recipe.json"]}</pre>
      <h3>Python analysis</h3><pre>{source}</pre>
    </details>}
    <div className="assay-controls">
      {release && local !== null && <button disabled={!!phase} onClick={run}><Play size={16}/> {result ? "Run again" : "Run on simulator"}</button>}
      <span role="status">{phase || (result ? "Analysis complete" : "")}</span>
    </div>
    {error && <p className="ws-alert" role="alert">{error}</p>}
    {result && <div className="assay-estimate">
      <h3>Vial A concentration</h3>
      <strong>{result.status === "ok" ? result.concentration_mg_l.toFixed(2) + " mg/L" : "Concentration withheld"}</strong>
      <p>{result.status === "ok" ? "Estimated from the three absorbance readings below." : "A reading is outside the calibrated range."}</p>
    </div>}
    {acquisition && <div className="table-scroll"><table>
      <caption>Simulated detector readings</caption>
      <thead><tr>{["Reading","Dark counts","Blank counts","Sample counts","Absorbance"].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
      <tbody>{acquisition.raw.map((r,i) => <tr key={r.replicate}><th scope="row">{r.replicate}</th><td>{r.dark_counts}</td><td>{r.blank_counts}</td><td>{r.sample_counts}</td><td>{acquisition.analysis_input.absorbances[i].toFixed(5)}</td></tr>)}</tbody>
    </table></div>}
    {report && <button className="assay-download" onClick={() => downloadEvidence({application:release, acquisition, analysis:report, paper})}><Download size={15}/> Download run evidence</button>}
  </section>
  <section className="workspace-card">
    <h2>Paper comparison</h2>
    <p>Laganovska and colleagues measured B12 samples of known concentration with a {paper.instrument} at {paper.wavelength} nm.</p>
    {report ? <details className="paper-example"><summary>Show paper comparison</summary>
      <p>For their {paper.sample.prepared_ppm} ppm sample, the paper reports a mean absorbance of <strong>{paper.sample.mean_absorbance.toFixed(3)}</strong>. The generated app used the same calibration to analyze that reading.</p>
      <dl className="assay-facts paper-facts">
        <div><dt>Paper preparation</dt><dd>{paper.sample.prepared_ppm} ppm</dd></div>
        <div><dt>App estimate</dt><dd>{paperEstimate == null ? "Withheld" : paperEstimate.toFixed(2) + " mg/L"}</dd></div>
        {difference != null && <div><dt>Difference</dt><dd>{Math.abs(difference).toFixed(2)} mg/L {difference > 0 ? "high" : difference < 0 ? "low" : ""}</dd></div>}
      </dl>
      <p>For this aqueous sample, {paper.sample.prepared_ppm} ppm is approximately {paper.sample.prepared_ppm} mg/L. Our calibration predicts an absorbance of <strong>{(acquisition.analysis_input.calibration.slope * paper.sample.prepared_ppm + acquisition.analysis_input.calibration.intercept).toFixed(3)}</strong> at that concentration. The paper measured <strong>{paper.sample.mean_absorbance.toFixed(3)}</strong>. That higher reading maps to a higher concentration on our curve. This comparison alone cannot identify the physical cause.</p>
      <a className="paper-link" href={"https://doi.org/" + paper.doi} target="_blank" rel="noreferrer">Laganovska et al. (2020), Table 1 · commercial instrument</a>
    </details> : <p className="paper-pending">Run the app to compare its estimate with the paper’s 10 ppm sample.</p>}
  </section></>;
}
