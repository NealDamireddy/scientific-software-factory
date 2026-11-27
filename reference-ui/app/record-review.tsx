"use client";

import { useRef, useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  Check,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  FileUp,
  Info,
  TriangleAlert,
} from "lucide-react";
import Modal from "./modal";
import {
  evidenceSkills,
  reviewEvidencePacket,
  type EvidencePacket,
} from "./review-skills/evidence";
import {
  finiteDecimal,
  maxFileBytes,
  parseRecordCsv,
  type Observation,
} from "./record-csv";
import "./record-review.css";

type SourceRecord = {
  source: string;
  observations: Observation[];
  csv: string;
  sha256: string;
};
type Report = {
  packet: EvidencePacket;
  findings: ReturnType<typeof reviewEvidencePacket>;
  selectedSkills: string[];
};
const perPage = 6;
const verdictLabels = {
  clear: "Clear",
  finding: "Finding",
  unassessed: "Unassessed",
};

function RecordPreview({ record }: { record: SourceRecord }) {
  const [page, setPage] = useState(0);
  const end = Math.min((page + 1) * perPage, record.observations.length);
  return (
    <section className="rr-preview" aria-label="CSV preview">
      <div className="rr-preview-head">
        <strong>
          <FileSpreadsheet size={16} />
          {record.source}
        </strong>
        <small>
          {record.observations.length}{" "}
          {record.observations.length === 1 ? "row" : "rows"}
        </small>
      </div>
      <div className="rr-digest">
        <strong>SHA-256</strong>
        <code>{record.sha256}</code>
      </div>
      <div
        className="rr-table-wrap"
        tabIndex={0}
        role="region"
        aria-label="Source data table"
      >
        <table>
          <thead>
            <tr>
              {["Row", "Sample", "Measurement", "Value", "Unit"].map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {record.observations.slice(page * perPage, end).map((obs) => (
              <tr key={obs.row}>
                <th scope="row">{obs.row}</th>
                {[obs.sample, obs.measurement, obs.value, obs.unit].map(
                  (cell, index) => (
                    <td key={index}>
                      {cell === null || cell === "" ? (
                        <span aria-label="Empty cell">—</span>
                      ) : (
                        cell
                      )}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {record.observations.length > perPage && (
        <div className="rr-pagination">
          <span>
            {page * perPage + 1}–{end} of {record.observations.length}
          </span>
          <button
            type="button"
            className="ws-iconbutton"
            aria-label="Previous rows"
            disabled={!page}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={17} />
          </button>
          <button
            type="button"
            className="ws-iconbutton"
            aria-label="Next rows"
            disabled={end === record.observations.length}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight size={17} />
          </button>
        </div>
      )}
    </section>
  );
}

export default function RecordReview({ close }: { close: () => void }) {
  const [record, setRecord] = useState<SourceRecord | null>(null);
  const [busy, setBusy] = useState(false),
    [fileError, setFileError] = useState("");
  const [selected, setSelected] = useState(() =>
    evidenceSkills.map((skill) => skill.id),
  );
  const [groupMean, setGroupMean] = useState(false);
  const [withClaim, setWithClaim] = useState(false),
    [claimError, setClaimError] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const reading = useRef(0),
    reportHeading = useRef<HTMLHeadingElement>(null);
  async function load(file: File | undefined) {
    const token = ++reading.current;
    setFileError("");
    setRecord(null);
    setReport(null);
    setBusy(false);
    setGroupMean(false);
    setWithClaim(false);
    setClaimError("");
    if (!file) return;
    if (file.size > maxFileBytes) {
      setFileError("Choose a CSV file of 1 MB or less.");
      return;
    }
    setBusy(true);
    try {
      const bytes = await file.arrayBuffer();
      if (token !== reading.current) return;
      let csv: string;
      try {
        csv = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
          bytes,
        );
      } catch {
        throw new Error("Choose a UTF-8 encoded CSV file.");
      }
      if (!crypto.subtle)
        throw new Error(
          "Open the workspace on localhost or HTTPS to verify the file digest.",
        );
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const sha256 = Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
      if (token !== reading.current) return;
      const observations = parseRecordCsv(csv);
      setRecord({ source: file.name, csv, observations, sha256 });
    } catch (error) {
      if (token === reading.current)
        setFileError(
          error instanceof Error ? error.message : "The CSV could not be read.",
        );
    } finally {
      if (token === reading.current) setBusy(false);
    }
  }
  function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!record || !selected.length) return;
    let claim: EvidencePacket["claim"];
    if (withClaim && selected.includes("claim-evidence")) {
      const data = new FormData(event.currentTarget);
      const get = (field: string) => String(data.get(field) ?? "").trim();
      const sample = get("sample"),
        measurement = get("measurement"),
        unit = get("unit"),
        value = finiteDecimal(get("value"));
      if (!sample || !measurement || !unit || value === null) {
        setClaimError(
          "Enter the sample, measurement, finite value, and unit for the claim.",
        );
        return;
      }
      claim = {
        sample,
        measurement,
        value,
        unit,
        ...(groupMean ? { statistic: "mean" as const } : {}),
      };
    }
    const packet: EvidencePacket = {
      source: record.source,
      observations: record.observations,
      ...(claim ? { claim } : {}),
    };
    setReport({
      packet,
      findings: reviewEvidencePacket(packet, selected),
      selectedSkills: [...selected],
    });
    requestAnimationFrame(() => reportHeading.current?.focus());
  }
  function download() {
    if (!report || !record) return;
    const data = {
      schemaVersion: 1,
      scope: "local-read-only-record-review",
      ...report,
      sourceCsv: record.csv,
      sourceSha256: record.sha256,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download =
      (record.source.replace(/\.csv$/i, "") || "measurement") + "-review.json";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Modal title="Review a record" close={close} className="rr-dialog">
      <p className="rr-intro">
        Check a measurement CSV locally. This read-only review keeps your file
        in this browser.
      </p>
      <form onSubmit={run}>
        <section className="rr-source">
          <div className="rr-section-head">
            <h3>Source record</h3>
            <a href="/examples/measurement-record.csv" download>
              Example CSV
              <ArrowDownToLine size={14} />
            </a>
          </div>
          <label className="rr-upload">
            <FileUp size={18} />
            <span>{record ? "Replace CSV file" : "Choose CSV file"}</span>
            <input
              type="file"
              aria-label="Choose CSV file"
              accept=".csv,text/csv"
              onChange={(e) => void load(e.currentTarget.files?.[0])}
            />
          </label>
          <p className="rr-schema">
            Columns <code>sample,measurement,value,unit</code>
            <br />
            Up to 1 MB and 1,000 data rows.
          </p>
          {fileError && <p role="alert">{fileError}</p>}
          {busy && <p role="status">Reading file…</p>}
          {record && <RecordPreview key={reading.current} record={record} />}
        </section>
        <fieldset className="rr-checks">
          <legend>Skills for this review</legend>
          {evidenceSkills.map((skill) => (
            <label className="rr-check" key={skill.id}>
              <input
                type="checkbox"
                checked={selected.includes(skill.id)}
                onChange={() => {
                  if (skill.id === "claim-evidence") {
                    setGroupMean(false);
                    setWithClaim(false);
                    setClaimError("");
                  }
                  setReport(null);
                  setSelected((old) =>
                    old.includes(skill.id)
                      ? old.filter((id) => id !== skill.id)
                      : [...old, skill.id],
                  );
                }}
              />
              <span>
                <strong>{skill.name}</strong>
                <small>{skill.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {selected.includes("claim-evidence") && (
          <section className="rr-claim">
            <label className="rr-check">
              <input
                type="checkbox"
                checked={withClaim}
                onChange={(e) => {
                  setGroupMean(false);
                  setWithClaim(e.target.checked);
                  setReport(null);
                  setClaimError("");
                }}
              />
              <span>Add a numeric claim</span>
            </label>
            {withClaim && (
              <div
                className="rr-fields"
                onChange={() => {
                  setReport(null);
                  setClaimError("");
                }}
              >
                <div className="rr-comparison">
                  <label className="ws-field">
                    Comparison
                    <select
                      value={groupMean ? "mean" : "single"}
                      onChange={(e) => setGroupMean(e.target.value === "mean")}
                    >
                      <option value="single">Single observation</option>
                      <option value="mean">Group mean</option>
                    </select>
                  </label>
                  {groupMean && (
                    <p>
                      The mean uses all rows matching the sample or group,
                      measurement, and unit.
                    </p>
                  )}
                </div>
                {["sample", "measurement", "value", "unit"].map((field) => (
                  <label key={field} className="ws-field">
                    {groupMean && field === "sample"
                      ? "Sample or group"
                      : field[0].toUpperCase() + field.slice(1)}
                    <input
                      name={field}
                      type="text"
                      inputMode={field === "value" ? "decimal" : "text"}
                      required
                      maxLength={field === "value" ? 80 : 512}
                    />
                  </label>
                ))}
              </div>
            )}
            {claimError && <p role="alert">{claimError}</p>}
          </section>
        )}
        <div className="rr-run">
          {!selected.length && <small>Select a skill to run the review.</small>}
          <button
            className="ws-button primary"
            type="submit"
            disabled={busy || !record || !selected.length}
          >
            Run review
          </button>
        </div>
      </form>
      {report && (
        <section className="rr-results" aria-label="Review results">
          <div className="rr-section-head">
            <h3 ref={reportHeading} tabIndex={-1}>
              Review results
            </h3>
            <button className="ws-button" onClick={download}>
              <ArrowDownToLine size={15} />
              Download JSON
            </button>
          </div>
          {report.findings.map((f) => {
            const Icon =
              f.verdict === "clear"
                ? Check
                : f.verdict === "finding"
                  ? TriangleAlert
                  : Info;
            return (
              <article key={f.skillId}>
                <div className="rr-result-head">
                  <h4>
                    {evidenceSkills.find((s) => s.id === f.skillId)?.name}
                  </h4>
                  <span className={"rr-verdict rr-" + f.verdict}>
                    <Icon size={14} />
                    {verdictLabels[f.verdict]}
                  </span>
                </div>
                <p>{f.finding}</p>
                {f.references.length > 0 && (
                  <div className="rr-refs">
                    <strong>Source references</strong>
                    {f.references.length <= 4 ? (
                      <ul>
                        {f.references.map((ref) => (
                          <li key={ref}>{ref}</li>
                        ))}
                      </ul>
                    ) : (
                      <details>
                        <summary>{f.references.length} references</summary>
                        <ul>
                          {f.references.map((ref) => (
                            <li key={ref}>{ref}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
              </article>
            );
          })}
          <div className="rr-done">
            <button className="ws-button" type="button" onClick={close}>
              Done
            </button>
          </div>
        </section>
      )}
    </Modal>
  );
}
