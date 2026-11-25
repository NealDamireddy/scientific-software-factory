import { readFileSync } from "node:fs";
import path from "node:path";
import { ArrowLeft, ArrowUpRight, Download } from "lucide-react";

export const metadata = { title: "Archived B12 assay · EVOLVE" };

const style = `
.b12{color:#1b342a;background:#f5f5ed;min-height:100vh;--card:#fffefa;--line:#d3d9cb;--muted:#55695b;--leaf:#195b46;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
.b12 *{box-sizing:border-box}.b12 h1,.b12 h2,.b12 h3,.b12 p,.b12 dl,.b12 figure{margin:0}.b12 a,.b12 summary{color:var(--leaf)}.b12 summary{cursor:pointer}.b12 a:focus-visible,.b12 summary:focus-visible,.b12 pre:focus-visible{outline:3px solid #bc682e;outline-offset:3px}
.b12 .wrap{max-width:1090px;margin:0 auto;padding-inline:clamp(16px,4vw,50px)}.b12 header{background:#19372f;color:#f8f8e9}.b12 header .wrap{display:flex;align-items:center;justify-content:space-between;min-height:60px}.b12 header strong{font-size:22px;letter-spacing:-.07em}.b12 header a{color:#ddedd6;display:inline-flex;align-items:center;gap:6px;font-size:13px}.b12 main.wrap{padding-block:32px 48px}
.b12 .eyebrow,.b12 .badge,.b12 code,.b12 pre{font-family:var(--mono)}.b12 .eyebrow{color:var(--muted);font-size:11px;letter-spacing:.09em;text-transform:uppercase;font-weight:650}.b12 h1{font-size:clamp(45px,6vw,78px);line-height:1.04;letter-spacing:-.07em;font-weight:620}.b12 .lede{color:var(--muted);font-size:18px;max-width:68ch;line-height:1.45;margin-top:10px}.b12 .tags,.b12 .actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px}.b12 .tags{margin-bottom:12px}.b12 .badge{background:#dfead9;border-radius:5px;color:#26533e;font-size:11px;line-height:1.4;padding:4px 7px}.b12 .actions{margin-top:15px}.b12 .actions a{display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid #8fa591;border-radius:6px;font-size:14px;font-weight:600}.b12 .actions .primary{color:#fff;background:var(--leaf);border-color:var(--leaf)}
.b12 section{margin-top:22px}.b12 .card{padding:clamp(16px,2.4vw,26px);border:1px solid var(--line);border-radius:11px;background:var(--card);min-width:0}.b12 .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.b12 h2{font-size:clamp(21px,2.5vw,30px);letter-spacing:-.05em;line-height:1.16;margin:6px 0 10px}.b12 h3{font-size:16px;letter-spacing:-.015em;margin:11px 0 4px}.b12 .copy,.b12 dd,.b12 li,.b12 details,.b12 .note{font-size:14px;line-height:1.5}.b12 .note{color:var(--muted);margin-top:8px}.b12 .result{background:#1e4336;color:#f4f8e6;display:grid;grid-template-columns:1fr 1.35fr;gap:16px;align-items:center}.b12 .result .eyebrow{color:#c5d7bd}.b12 .result h2{font-size:clamp(32px,5vw,58px);letter-spacing:-.055em;margin-bottom:0}.b12 .result h2 small{font-size:.42em;letter-spacing:-.025em;font-weight:500}.b12 .facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:10px}.b12 .facts dt{font-size:12px;color:#cadec6}.b12 .facts dd{margin:2px 0;font-weight:650;font-size:16px}.b12 code{font-size:12px;overflow-wrap:anywhere}.b12 table{border-collapse:collapse;width:100%;font-size:14px}.b12 caption{text-align:left;font-size:14px;font-weight:600;margin-bottom:7px}.b12 th,.b12 td{text-align:left;border-bottom:1px solid var(--line);padding:6px 4px}.b12 .pass{color:#235b40}.b12 .fail{color:#8b4326}.b12 .inline-facts{display:grid;grid-template-columns:minmax(90px,max-content) minmax(0,1fr);gap:5px 12px}.b12 .inline-facts dt{color:var(--muted);font-size:13px}.b12 dd{margin:0;overflow-wrap:anywhere}.b12 .divider{border-top:1px solid var(--line);margin-top:13px;padding-top:10px}.b12 details{margin-top:10px}.b12 summary{font-weight:620}.b12 pre{background:#19352c;color:#edf7e3;padding:12px;border-radius:6px;overflow:auto;max-height:330px;font-size:12px;line-height:1.5;tab-size:4}
@media(max-width:660px){.b12 .grid,.b12 .result{grid-template-columns:1fr}.b12 main.wrap{padding-top:22px}.b12 .inline-facts{grid-template-columns:1fr;gap:1px}.b12 .inline-facts dd{margin-bottom:5px}.b12 .facts{grid-template-columns:repeat(3,minmax(0,1fr))}.b12 .facts dd{font-size:14px}}
`;

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
      <div style={{overflowX:"auto",maxWidth:"100%"}} tabIndex="0" role="region" aria-label="Published benchmark table">
        <table style={{minWidth:"475px"}}>
          <thead><tr><th scope="col">Prepared (ppm)</th><th scope="col">Absorbance</th><th scope="col">Estimate (mg/L)</th><th scope="col">Error (mg/L)</th><th scope="col">Range</th></tr></thead>
          <tbody>{published.rows.map(row => <tr key={row.id}>
            <th scope="row">{number(row.prepared_ppm)}</th>
            <td>{row.mean_absorbance.toFixed(3)}</td><td>{number(row.predicted_mg_l)}</td>
            <td>{signed(row.signed_error_mg_l)}</td><td>{row.extrapolated ? "Extrapolated" : "In range"}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="actions"><a href="/b12/evaluation/predictions.json" download>Recorded predictions</a><a href="/b12/evaluation/report.json" download>Scored evaluation</a></div>
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
    <style>{style}</style>
    <header><div className="wrap"><strong>EVOLVE</strong><a href="/epr/"><ArrowLeft size={15}/> EPR workbench</a></div></header>
    <main className="wrap">
      <div className="tags"><span className="badge">Previous completed run</span><span className="eyebrow">Simulated instrument · 550 nm</span></div>
      <h1>Vitamin B12 assay</h1>
      <p className="lede">A mystery vial exceeded the direct assay’s calibration range. The PI approved a dilution, and a local coding worker added prepared-sample support to the assay.</p>
      <div className="actions">
        <a className="primary" href="/b12/demo/">Run online instrument demo</a>
        <a download href="/b12/completed.json"><Download size={16}/> Download run evidence</a>
        <a href="http://127.0.0.1:8765/" target="_blank" rel="noreferrer">Open local presenter <ArrowUpRight size={15}/></a>
      </div>
      <p className="note">Fresh generation runs on the presenter laptop with <code>python -m factory.lab</code>.</p>
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
