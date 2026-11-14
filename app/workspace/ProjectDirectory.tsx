import { ArrowRight, AudioWaveform, BookOpen, FlaskConical, Pipette, Radio } from "lucide-react";

export const projects = [
  { id: "visible-assay", name: "Visible absorbance assay", description: "Measure sample concentration and follow its change over time using UV–Vis absorbance.", icon: AudioWaveform },
  { id: "empty-assay", name: "Assay development", description: "Design an experiment, define its outputs, and prepare a new assay application.", icon: Pipette },
];

export function projectName(id: string) {
  return projects.find(project => project.id === id)?.name ?? id;
}

export default function ProjectDirectory() {
  return <>
    <div className="project-grid">
      {projects.map(({ id, name, description, icon: Icon }, index) => (
        <a key={id} className="project-tile" href={"/workspace/?project=" + id}>
          <div className={"project-cover " + (index === 0 ? "spectrum" : "plate")} aria-hidden="true">
            {index === 0 ? <div className="spectrum-bars">{Array.from({length: 68}, (_, i) => {
              const peak = (center: number, width: number) => Math.exp(-((i - center) ** 2) / width);
              return <i key={i} style={{height: (7 + 50 * peak(17, 45) + 80 * peak(39, 68) + 20 * peak(56, 20)) + "%"}} />;
            })}</div> : <div className="well-plate">{Array.from({length: 48}, (_, i) => <i key={i} />)}</div>}
          </div>
          <div className="project-copy"><div className="project-title"><Icon size={20}/><h2>{name}</h2></div><p>{description}</p>
            <span className="project-open">Open project <ArrowRight size={16}/></span>
          </div>
        </a>
      ))}
    </div>
    <a className="instrument-project" href="/b12/demo/"><FlaskConical size={25}/>
      <span><strong>Vitamin B12 assay</strong><small>Run a generated application on the online 550 nm instrument simulator.</small></span>
      <span className="project-open">Open demo <ArrowRight size={16}/></span>
    </a>
  </>;
}

export function Archives() {
  return <section className="archive-directory"><h2><BookOpen size={18}/> Lab archives</h2>
    <div>{[
      { name: "EPR archive", detail: "Spectra, work orders and replay", url: "/epr/", icon: Radio },
      { name: "B12 archive", detail: "Vitamin B12 assay and run evidence", url: "/b12/", icon: FlaskConical },
    ].map(({name,detail,url,icon:Icon}) => <a key={url} href={url}><Icon size={21}/><span><strong>{name}</strong><small>{detail}</small></span><ArrowRight size={16}/></a>)}</div>
  </section>;
}
