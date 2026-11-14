import {readFileSync} from "node:fs";
import {ChevronRight, FlaskConical, LayoutGrid} from "lucide-react";
import Demo from "./Demo";
import "../../workspace/workspace.css";
import "./demo.css";

export const metadata = {title: "Vitamin B12 assay · EVOLVE"};

export default function Page() {
  const bundle = JSON.parse(readFileSync("public/b12/completed.json", "utf8"));
  const {published} = JSON.parse(readFileSync("data/b12-evaluation.json", "utf8"));
  const {direct, initial, sources} = bundle;
  const release = {revision: direct.revision, files: sources[direct.id].files};
  const recipe = JSON.parse(release.files["recipe.json"]);
  const standards = initial.calibration.standards;
  const paper = {
    sample: published.samples.find(sample => sample.prepared_ppm === 10),
    instrument: published.instrument,
    wavelength: published.wavelength_nm,
    doi: published.doi,
  };

  return <div className="workspace b12-demo">
    <header className="ws-top"><div><a className="ws-brand" href="/"><FlaskConical size={24}/> EVOLVE</a><span className="ws-lab">Northfield laboratory</span></div></header>
    <main>
      <nav className="breadcrumb" aria-label="Breadcrumb"><LayoutGrid size={15}/><a href="/">Lab projects</a><ChevronRight size={14}/>Vitamin B12 assay</nav>
      <div className="directory-heading"><div><h1>Vitamin B12 assay</h1><p>How much vitamin B12 is in Vial A?</p></div></div>
      <section className="workspace-card">
        <h2>Experiment specifications</h2>
        <p>Measure how much light the sample absorbs, then use known B12 standards to estimate its concentration.</p>
        <dl className="assay-facts">
          <div><dt>Sample</dt><dd>Vial A · aqueous B12</dd></div>
          <div><dt>Simulated instrument</dt><dd>{recipe.wavelength_nm} nm spectrophotometer</dd></div>
          <div><dt>Measurement</dt><dd>{recipe.replicates} readings · {standards[0].raw[0].settings.path_length_mm} mm light path</dd></div>
          <div><dt>Calibration standards (mg/L)</dt><dd>{standards.map(s => s.concentration_mg_l).join(", ")}</dd></div>
        </dl>
      </section>
      <Demo savedRelease={release} paper={paper} preset={{
        application_name: "Vitamin B12 concentration", sample: "Vial A", analyte: "vitamin B12",
        wavelength_nm: recipe.wavelength_nm, readings: recipe.replicates,
        light_path_mm: standards[0].raw[0].settings.path_length_mm,
        standards_mg_l: standards.map(s => s.concentration_mg_l),
        output: "concentration in mg/L; withhold outside calibration",
      }}/>
    </main>
  </div>;
}
