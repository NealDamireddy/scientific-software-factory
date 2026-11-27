import { readFileSync } from "node:fs";
import path from "node:path";
import { evolvePath, inLabFactory } from "../paths";
import "./archive.css";
import { ArrowLeft, ArrowUpRight, Download } from "lucide-react";

export const metadata = { title: "Archived B12 assay · EVOLVE" };

function number(value, precision = 3) {
  return typeof value === "number" && Number.isFinite(value) ? Number(value.toFixed(precision)).toString() : "Unavailable";
}

function signed(value) {
  return typeof value === "number" && value > 0 ? "+" + number(value) : number(value);
}

function Count({ suite }) {
  return <>{suite.filter(check => check.pass).length} / {suite.length}</>;
}

function Marks({ check }) {
  if (!check) return <span>Absent</span>;
  return <strong className={check.pass ? "pass" : "fail"}>{check.pass ? "Pass" : "Fail"}</strong>;
}

function Source({ title, source }) {
  return <details><summary>{title}</summary><pre tabIndex="0" aria-label={title}>{source}</pre></details>;
}

function Evaluation({ report }) {
  const { panel, published } = report;
  return <section className="card" aria-labelledby="evaluation-heading">
    <p className="eyebrow">Supporting evaluation</p>
    <h2 id="evaluation-heading">How far did the estimates miss?</h2>
    <p className="copy">Across the blind simulated panel, the mean absolute error was <strong>{number(panel.mae_mg_l)} mg/L</strong>, against a target of {number(panel.target_mae_mg_l)} mg/L. On the six published commercial-instrument means, the same frozen calibration gave a mean absolute error of <strong>{number(published.mae_mg_l)} mg/L</strong>.</p>
    <details>
      <summary>Inspect six published readings and their errors</summary>
      <p className="note">Signed error is the estimate minus the prepared concentration. The benchmark includes extrapolations for scoring. The live assay withholds an out-of-range result for PI review. The six means measure transfer across conditions. Their differences have several possible causes. <a href="https://doi.org/10.1016/j.ohx.2020.e00108">Laganovska et al., Table 1 (“Com”)</a></p>
      <div className="benchmark-table" tabIndex="0" role="region" aria-label="Published benchmark table">
        <table>
          <thead><tr><th scope="col">Prepared (ppm)</th><th scope="col">Absorbance</th><th scope="col">Estimate (mg/L)</th><th scope="col">Error (mg/L)</th><th scope="col">Range</th></tr></thead>
          <tbody>{published.rows.map(row => <tr key={row.id}>
            <th scope="row">{number(row.prepared_ppm)}</th>
            <td>{row.mean_absorbance.toFixed(3)}</td><td>{number(row.predicted_mg_l)}</td>
            <td>{signed(row.signed_error_mg_l)}</td><td>{row.extrapolated ? "Extrapolated" : "In range"}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="actions"><a href={evolvePath("/b12/evaluation/predictions.json")} download>Recorded predictions</a><a href={evolvePath("/b12/evaluation/report.json")} download>Scored evaluation</a></div>
    </details>
  </section>;
}

export default function B12Archive() {
  const evidence = JSON.parse(readFileSync(path.join(process.cwd(), "public", "b12", "completed.json"), "utf8"));
  const evaluation = JSON.parse(readFileSync(path.join(process.cwd(), "public", "b12", "evaluation", "report.json"), "utf8"));
  const { direct, initial, followup, sources } = evidence;
  const { approval, checks, measurement, parent_checks: parentChecks, preparation, replay, result, score } = followup;
  const proposal = direct.proposal;
  const revisionFiles = sources[followup.id];
  const fixtures = ["prepared-2x", "prepared-4x"];
  const checksByName = new Map(checks.map(check => [check.name, check]));
  const parentChecksByName = new Map(parentChecks.map(check => [check.name, check]));
  const acquisition = measurement.finding.absorbances.map(value => number(value, 5)).join(", ");
  const context = followup.context;
  return <div className="b12">
    <header><div className="wrap"><strong>EVOLVE</strong><a href={evolvePath("/")}><ArrowLeft size={15}/> EPR workbench</a></div></header>
    <main className="wrap">
      <div className="tags"><span className="badge">Previous completed run</span><span className="eyebrow">Simulated instrument · 550 nm</span></div>
      <h1>Vitamin B12 assay</h1>
      <p className="lede">A mystery vial exceeded the direct assay’s calibration range. The PI approved a dilution, and a local coding worker added prepared-sample support to the assay.</p>
      <div className="actions">
        <a className="primary" download href={evolvePath("/b12/completed.json")}><Download size={16}/> Download run evidence</a>
        {inLabFactory
          ? <a href="/#b12">Review B12 analyses in Lab Factory <ArrowUpRight size={15}/></a>
          : <a href="http://127.0.0.1:8765/" target="_blank" rel="noreferrer">Open local presenter <ArrowUpRight size={15}/></a>}
      </div>
      {!inLabFactory && <p className="note">Fresh generation runs on the presenter laptop with <code>python -m factory.lab</code>.</p>}
      <section className="card result" aria-labelledby="result-heading">
        <div><p className="eyebrow">Original vial · {result.parent_id || preparation.parent_id}</p>
          <h2 id="result-heading">{result.status === "ok" ? <>{number(result.concentration_mg_l)} <small>mg/L</small></> : "Measurement requires review"}</h2>
        </div>
        <dl className="facts">
          <div><dt>Diluted vial</dt><dd>{number(result.diluted_mg_l)} mg/L</dd></div>
          <div><dt>Revealed label</dt><dd>{score ? number(score.prepared_mg_l) + " mg/L" : "Withheld"}</dd></div>
          <div><dt>Signed error</dt><dd>{score ? signed(score.signed_error_mg_l) + " mg/L" : "Unavailable"}</dd></div>
        </dl>
      </section>
      <section className="grid" aria-label="Experiment and development records">
        <article className="card"><p className="eyebrow">Experiment track</p><h2>From finding to follow-up</h2>
          <h3>Initial measurement</h3><p className="copy">Absorbances {initial.input.absorbances.map(v => number(v, 5)).join(", ")} exceeded the highest calibration standard, {number(initial.calibration.high, 5)}.</p>
          <h3>PI decision</h3><p className="copy">{proposal.reason} The PI approved the {approval.factor}× preparation under <code>{approval.protocol}</code>.</p>
          <h3>Recorded preparation</h3><p className="copy">Vial {preparation.sample_id} contains {preparation.sample_ml} mL from {preparation.parent_id} in {preparation.final_ml} mL total. Its three new absorbances were {acquisition}.</p>
        </article>
        <article className="card"><p className="eyebrow">Software track</p><h2>Direct samples to prepared samples</h2>
          <p className="copy">{proposal.requirement}</p>
          <p className="note">The same independent fixtures ran on both source versions. Each checks the corrected concentration and links to the original vial.</p>
          <table><caption>Prepared-sample requirements</caption><thead><tr><th scope="col">Fixture</th><th scope="col">v1</th><th scope="col">v2</th></tr></thead>
            <tbody>{fixtures.map(name => <tr key={name}><th scope="row">{name === "prepared-2x" ? "Twofold dilution" : "Fourfold dilution"}</th><td><Marks check={parentChecksByName.get(name)}/></td><td><Marks check={checksByName.get(name)}/></td></tr>)}</tbody>
          </table>
          <p className="note">Verified v2 passed <Count suite={checks}/> checks. Its worker receipt identifies {followup.worker.cli} and {followup.worker.model}.</p>
          <Source title="Inspect the v1 → v2 source diff" source={revisionFiles.diff}/>
        </article>
      </section>
      <section className="card" aria-labelledby="evidence-heading">
        <p className="eyebrow">Reproducibility evidence</p><h2 id="evidence-heading">Readings, software and provenance</h2>
        <dl className="inline-facts">
          <dt>Lab / project</dt><dd>{context.lab} / {context.project}</dd>
          <dt>Instrument</dt><dd>{context.instrument_profile} · {context.protocol}</dd>
          <dt>Direct task / source</dt><dd><code>{direct.id}</code><br/><code>{direct.revision}</code></dd>
          <dt>Follow-up task / source</dt><dd><code>{followup.id}</code><br/><code>{followup.revision}</code></dd>
          <dt>Frozen calibration</dt><dd><code>{measurement.calibration_id}</code></dd>
          <dt>Replay outcome</dt><dd>{replay ? "Direct run " + (replay.parent_matches ? "matched" : "differed") + ". Follow-up " + (replay.child_matches ? "matched." : "differed.") : "No replay outcome recorded."}</dd>
          <dt>Scientific review</dt><dd>{evidence.scientific_review.join(" ")}</dd>
        </dl>
        <div className="divider">
          <Source title="Inspect initial and follow-up readings" source={JSON.stringify({initial: initial.raw, followup: measurement.raw}, null, 2)}/>
          <Source title="Inspect independent verification results" source={JSON.stringify({parent: parentChecks, candidate: checks}, null, 2)}/>
          <Source title="Inspect the released analysis module" source={revisionFiles.files["analysis.py"]}/>
        </div>
      </section>
      <Evaluation report={evaluation}/>
    </main>
  </div>;
}
