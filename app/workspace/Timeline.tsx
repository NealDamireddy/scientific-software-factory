import type { Run } from "./api";

const lanes = [
  ["software", "Software preparation"],
  ["acquisition", "Data collection"],
  ["analysis", "Analysis"],
] as const;

function instant(value: string | null) {
  const ms = value && Date.parse(value);
  return typeof ms === "number" && Number.isFinite(ms) ? ms : null;
}

export function Timeline({ run }: { run: Run }) {
  const rows = lanes.map(([key, label]) => ({
    key, label, state: run[key],
    start: instant(run[`${key}_started_at`]),
    end: instant(run[`${key}_finished_at`]),
  }));
  const times = rows.flatMap(row => [row.start, row.end]).filter(t => t !== null);
  const origin = Math.min(...times);
  const end = Math.max(...times);
  const elapsed = (t: number) => (t - origin) / 1000;
  const position = (t: number) => end > origin ? 100 * (t - origin) / (end - origin) : 0;
  const [software, acquisition] = rows;
  const wait = run.software === "ready" && run.acquisition === "completed" &&
    software.end !== null && acquisition.end !== null ? (software.end - acquisition.end) / 1000 : null;
  const overlap = software.start !== null && software.end !== null && acquisition.start !== null && acquisition.end !== null
    ? (Math.min(software.end, acquisition.end) - Math.max(software.start, acquisition.start)) / 1000 : null;
  return <section className="timing" aria-label="Factory timeline">
    <h3>Factory timeline</h3>
    <p className="timeline-origin">Seconds from first recorded stage event</p>
    {rows.map(({key,label,state,start,end:finish}) => {
      const interval = start !== null && finish !== null && finish > start;
      const when = start !== null && finish !== null && finish >= start
        ? `${elapsed(start)}–${elapsed(finish)} s`
        : start !== null ? `Start ${elapsed(start)} s` : finish !== null ? `End ${elapsed(finish)} s` : "Timing unavailable";
      return <div className="lane" key={key}>
        <div><strong>{label}</strong><small>{state} · {when}</small></div>
        <div className="track" aria-hidden="true">
          {interval ? <i className={key} style={{left: position(start) + "%", width: (position(finish) - position(start)) + "%"}}/> :
            (start ?? finish) !== null && <i className="point" style={{left: position((start ?? finish)!) + "%"}}/>}
        </div>
      </div>;
    })}
    {!!times.length && <div className="axis" aria-hidden="true"><span>0 s</span>{end > origin && <span>{elapsed(end)} s</span>}</div>}
    {overlap !== null && overlap > 0 && <p>Preparation and collection overlapped for <b>{overlap} s</b>.</p>}
    {wait !== null && wait > 0 && <p>Data waited <b>{wait} s</b> for software.</p>}
    {run.software_wait_pending && run.software_wait_s !== null && <p>Waiting for software · {run.software_wait_s} s at last update</p>}
  </section>;
}
