export const apiUrl = (path: string) => "/api/" + path;

export async function researchRequest<T>(
  path: string,
  body?: object,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    credentials: "include",
    cache: "no-store",
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error(
      "The Lab Factory API did not return JSON. Check the research workspace connection.",
    );
  }
  const data = await response.json();
  if (response.status === 202 && data.state === "drafting") {
    throw new Error(
      `Draft ${data.order.id} is being prepared. Retry with the same inputs to check its progress.`,
    );
  }
  if (!response.ok) {
    const pending = data.order_id
      ? ` Draft ${data.order_id} is saved. Retry with the same inputs to resume.`
      : "";
    throw new Error(
      (data.error || `Request failed (HTTP ${response.status}).`) + pending,
    );
  }
  return data;
}

export type RequestSummary = { id: string; objective: string; status: string };
export type RegisteredExperiment = {
  id: string;
  title: string;
  revision: number;
  lab_id: string;
};
export type AnalysisApp = RequestSummary & {
  project_id?: string | null;
  turn: number;
  artifact_digest?: string;
  contexts: { experiment: { title: string; revision: number };
    lab: {name:string; revision:number; instruments: {name:string; model:string; firmware:string}[]};
    stage_calibration?: { origin_mm: number; reading_unit?: string; ticks_per_mm?: number };
    briefing?: unknown }[];
  history: {
    turn: number;
    submission: { question: string; summary: string };
    answer: string | null;
  }[];
};
type Passage = {
  document: string;
  passage: number;
  title: string;
  text: string;
};
type ProcedureStep = {
  text: string;
  citations?: string[];
  amounts?: { what: string; value: number; unit: string }[];
  action?: {
    instrument_id: string;
    command: string;
    settings: { parameter: string; value: number; unit: string }[];
  };
  evidence?: { document: string; passage: number; quote: string }[];
};
export type Procedure = {
  order: RequestSummary & {
    experiment_id: string;
    experiment_revision: number;
  };
  state: string;
  question: string | null;
  question_step: number | null;
  previous_order: string | null;
  next_order: string | null;
  submission: { number: number; artifact: { steps?: ProcedureStep[] } } | null;
  documents: { id: string; title: string; kind: string }[];
  sources: Passage[];
};
