import { useState } from "react";
import { verifiedResult, type Run } from "./api";

export default function RefineData({runs}: {runs: Run[]}) {
  const [query, setQuery] = useState("");
  const [review, setReview] = useState("all");
  const rows = runs.flatMap(run => {
    const result = verifiedResult(run);
    return result ? result.results.map(row => ({run, row, unit: result.unit})) : [];
  });
  const visible = rows.filter(({row}) =>
    row.sample_id.toLowerCase().includes(query.trim().toLowerCase()) &&
    (review === "all" || (review === "withheld" ? row.concentration_mg_l === null : row.concentration_mg_l !== null)));
  return <section className="workspace-card refine"><h2>Refine data</h2>
    <p>Filter this project’s recorded measurements. Each value retains its source run and review finding.</p>
    <div className="field-grid"><label>Sample ID<input type="search" placeholder="Search samples" value={query} onChange={e => setQuery(e.target.value)}/></label>
      <label>Result status<select value={review} onChange={e => setReview(e.target.value)}><option value="all">All results</option><option value="reported">Reported concentration</option><option value="withheld">Withheld concentration</option></select></label></div>
    {visible.length > 0 ? <div className="table-scroll"><table><caption>{visible.length} {visible.length === 1 ? "measurement" : "measurements"}</caption><thead><tr>{["Sample","Run","Time (UTC)","Concentration","Review finding"].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
      {visible.map(({run,row,unit}, i) => <tr key={run.run_id + "/" + i}><td>{row.sample_id}</td><td>{run.run_id}</td><td>{row.timestamp ?? "—"}</td><td>{row.concentration_mg_l === null ? "Withheld" : row.concentration_mg_l + " " + unit}</td><td>{row.review_reason ?? "—"}</td></tr>)}
    </tbody></table></div> : <p role="status">{rows.length ? "No measurements match these filters." : "Measurements will appear here when a run has recorded results."}</p>}
  </section>;
}
