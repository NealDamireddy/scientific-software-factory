"use client";

import { Download } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { analysisMessage, completionLine, fitLine, readAnalysisResult, readingRows, resultLines } from "../lib/analysis.ts";
import type { AnalysisResult } from "../lib/analysis.ts";
import type { PlotSeries } from "../lib/plot.ts";
import { SAMPLE_READINGS, parseReadingsCsv, toCsv } from "../lib/readings.ts";
import type { Readings } from "../lib/readings.ts";
import type { AnalysisApp, ConnectorItem } from "../lib/types.ts";
import { ClientError } from "../lib/types.ts";
import { useClient, type CompletedAnalysis } from "./ClientContext.tsx";
import { Plot } from "./Plot.tsx";
import { runError, useRunner } from "./RunnerContext.tsx";
import { errorText } from "../lib/status.ts";

const SAMPLE_FILE = "coomassie-readings.csv";
const UNREADABLE = "The analysis app returned something that isn't a result.";

type Outcome =
  | { state: "running"; name: string }
  | CompletedAnalysis
  | { state: "error"; message: string; run: number };

function plotSeries(readings: Readings, result: AnalysisResult): PlotSeries[] {
  const points = readings.time_s.map((t, i): [number, number] => [t, readings.absorbance[i]]);
  const series: PlotSeries[] = [{ label: "Readings", points, style: "points" }];
  if (result.decay) series.push({ label: "Fit", points: fitLine(result, readings.time_s), style: "line" });
  return series;
}

function plotTable(readings: Readings, result: AnalysisResult) {
  return { columns: result.decay ? ["Readings", "Fit"] : ["Readings"], rows: readingRows(readings, result) };
}

function downloadSample() {
  const url = URL.createObjectURL(new Blob([toCsv(SAMPLE_READINGS)], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = SAMPLE_FILE;
  document.body.append(link);
  link.click();
  link.remove();
  // Give the download a moment to start before the URL goes.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Readings in, the analysis app's answer out: upload a CSV (or analyze readings from the instrument
 * data folder), and the app runs on this computer. Shows the result lines and a plot of the readings
 * with the app's fitted curve. Readings never leave the browser.
 */
export function ResultsView({ app, experimentId }: { app: AnalysisApp; experimentId: string }) {
  const { client, labId, mode, version, analysisHistory } = useClient();
  const run = useRunner();
  const uid = useId();
  const [outcome, setOutcome] = useState<Outcome | null>(() => {
    const previous = analysisHistory.get(experimentId);
    return previous?.code === app.code && previous.entry === app.entry ? previous.outcome : null;
  });
  const [folder, setFolder] = useState<ConnectorItem[] | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => () => { seq.current += 1; }, []);

  useEffect(() => {
    let live = true;
    client.listConnectors(labId).then(
      (connectors) => {
        if (!live) return;
        const c = connectors.find((x) => x.id === "instrument_folder");
        setFolder(c && c.connected ? c.items.filter((item) => item.kind === "readings") : null);
        setFolderError(null);
      },
      (e: unknown) => {
        if (live) setFolderError(errorText(e));
      },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  async function analyze(name: string, text: string, mine: number) {
    let readings: Readings;
    try {
      readings = parseReadingsCsv(text);
    } catch (e) {
      setOutcome({ state: "error", message: e instanceof ClientError ? e.message : runError(e), run: mine });
      return;
    }
    setOutcome({ state: "running", name });
    try {
      const value = await run(app.code, app.entry, { readings });
      if (mine !== seq.current) return;
      const result = readAnalysisResult(value);
      if (!result) {
        setOutcome({ state: "error", message: UNREADABLE, run: mine });
        return;
      }
      const completed: CompletedAnalysis = { state: "done", name, readings, result };
      analysisHistory.set(experimentId, { code: app.code, entry: app.entry, outcome: completed });
      setOutcome(completed);
    } catch (e) {
      if (mine === seq.current) setOutcome({ state: "error", message: analysisMessage(runError(e)), run: mine });
    }
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    // Cleared, so choosing the same file again runs it again.
    input.value = "";
    if (!file) return;
    const mine = ++seq.current;
    let text: string;
    try {
      text = await file.text();
    } catch {
      if (mine === seq.current) setOutcome({ state: "error", message: `Couldn't read ${file.name}.`, run: mine });
      return;
    }
    if (mine === seq.current) await analyze(file.name, text, mine);
  }

  const busy = outcome?.state === "running";
  return (
    <div className="compute">
      <h2 className="panel-heading">Results</h2>
      <p className="compute-summary">Readings stay in your browser. The analysis runs on this computer.</p>
      <div className="results-actions">
        <span className="results-upload">
          <label htmlFor={`${uid}-file`} className="results-upload-label">Upload readings (CSV)</label>
          <input id={`${uid}-file`} className="file-input" type="file" accept=".csv,text/csv" onChange={onFile} />
        </span>
        <button type="button" className="ws-button results-sample" onClick={downloadSample}>
          <Download size={16} aria-hidden="true" />
          <span>Download sample readings</span>
        </button>
      </div>

      {folder && folder.length > 0 && (
        <section className="results-folder" aria-labelledby={`${uid}-folder`}>
          <div className="results-folder-head">
            <h3 id={`${uid}-folder`} className="compute-subhead">From your instrument data folder</h3>
            {mode === "sample" && <span className="compute-tag">Sample connection</span>}
          </div>
          <ul className="results-folder-list" role="list">
            {folder.map((item) => (
              <li key={item.id}>
                <button type="button" className="ws-button hist-quiet results-analyze" onClick={() => void analyze(item.title, item.text, ++seq.current)}>
                  Analyze {item.title}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {folderError && <p role="alert" className="pg-error">Couldn&apos;t load your instrument data folder: {folderError}</p>}

      <p role="status" className="compute-status">
        {busy && "Running in your browser…"}
        {/* Hidden: the heading and result list below already say it on screen. */}
        {outcome?.state === "done" && <span className="visually-hidden">{completionLine(outcome.name, outcome.result)}</span>}
      </p>
      {/* Keyed by run, so the same error twice is a new alert and is announced again. */}
      {outcome?.state === "error" && <p key={outcome.run} role="alert" className="pg-error compute-alert">{outcome.message}</p>}
      {outcome?.state === "done" && (
        <section className="results-out" aria-labelledby={`${uid}-out`}>
          <h3 id={`${uid}-out`} className="compute-subhead">Analyzed {outcome.name}</h3>
          <ul className="results-lines" aria-label="Analysis results">
            {resultLines(outcome.result).map((line) => <li key={line}>{line}</li>)}
          </ul>
          <Plot title="Readings and fit" xLabel="Time (s)" yLabel="Absorbance (AU)" series={plotSeries(outcome.readings, outcome.result)} table={plotTable(outcome.readings, outcome.result)} />
        </section>
      )}
    </div>
  );
}
