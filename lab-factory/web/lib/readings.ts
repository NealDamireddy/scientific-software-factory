// Absorbance readings: a seeded synthetic generator, CSV output and a strict CSV parser.
import { ClientError } from "./types.ts";
import type { SyntheticParams } from "./types.ts";

export type Readings = { time_s: number[]; absorbance: number[] };

export const MISSING_COLUMNS_MESSAGE = "The file needs a time_s column and an absorbance column.";
export const TOO_FEW_READINGS_MESSAGE = "The analysis needs at least 5 readings.";
export const MIN_READINGS = 5;

export function notANumberMessage(row: number): string {
  return `Row ${row} has a value that isn't a number.`;
}

function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function round4(value: number): number {
  return Math.round(value * 1e4) / 1e4;
}

/** Readings that follow a0 → a_end with rate k, plus uniform noise in ±noise drawn from mulberry32(seed). */
export function syntheticReadings(p: SyntheticParams): Readings {
  const step = p.step_s ?? 10;
  const duration = p.duration_s ?? 600;
  if (!Number.isFinite(step) || !Number.isFinite(duration) || step <= 0 || duration < 0) {
    throw new ClientError("invalid", "The readings step and duration must be positive numbers.");
  }
  const rand = mulberry32(p.seed);
  const count = Math.floor(duration / step + 1e-9) + 1;
  const time_s: number[] = [];
  const absorbance: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const t = i * step;
    const value = p.a_end + (p.a0 - p.a_end) * Math.exp(-p.k * t) + p.noise * (2 * rand() - 1);
    time_s.push(round4(t));
    absorbance.push(round4(value));
  }
  return { time_s, absorbance };
}

export function toCsv(r: Readings): string {
  const lines = ["time_s,absorbance"];
  r.time_s.forEach((t, i) => lines.push(`${t},${r.absorbance[i]}`));
  return `${lines.join("\n")}\n`;
}

const NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/** Read logical records, retaining the starting physical line for errors on multiline fields. */
function* csvRows(text: string) {
  const input = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n") + "\n";
  let row = 1;
  let line = 1;
  let cells: string[] = [];
  let field = "";
  let quoted = false;
  let closed = false;
  for (let i = 0; i < input.length; i += 1) {
    const c = input[i];
    if (quoted) {
      if (c === '"' && input[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (c === '"') {
        quoted = false;
        closed = true;
      } else {
        field += c;
        if (c === "\n") line += 1;
      }
    } else if (c === "," || c === "\n") {
      cells.push(field.trim());
      field = "";
      closed = false;
      if (c === "\n") {
        if (cells.some((value) => value !== "")) yield { cells, row };
        cells = [];
        line += 1;
        row = line;
      }
    } else if (!closed && c === '"' && field.trim() === "") {
      quoted = true;
      field = "";
    } else if (c === '"' || (closed && c.trim() !== "")) {
      throw new ClientError("invalid", `Row ${row} has an invalid quoted field.`);
    } else {
      field += c;
    }
  }
  if (quoted) throw new ClientError("invalid", `Row ${row} has an unclosed quoted field.`);
}

/**
 * Parses a readings CSV. Columns may come in any order; blank lines and rows whose cells are all
 * empty are skipped. Row numbers are physical line numbers (the header is row 1 when no blank lines precede it). Throws ClientError("invalid") with the exact copy.
 */
export function parseReadingsCsv(text: string): Readings {
  const rows = csvRows(text);
  const first = rows.next();
  if (first.done) throw new ClientError("invalid", MISSING_COLUMNS_MESSAGE);
  const header = first.value.cells.map((name) => name.toLowerCase());
  const ti = header.indexOf("time_s");
  const ai = header.indexOf("absorbance");
  if (ti < 0 || ai < 0) throw new ClientError("invalid", MISSING_COLUMNS_MESSAGE);
  if (ti !== header.lastIndexOf("time_s") || ai !== header.lastIndexOf("absorbance")) {
    throw new ClientError("invalid", "The file needs exactly one time_s column and one absorbance column.");
  }
  const time_s: number[] = [];
  const absorbance: number[] = [];
  for (const { cells, row } of rows) {
    if (cells.length !== header.length) {
      throw new ClientError("invalid", `Row ${row} has ${cells.length} fields. The header has ${header.length}.`);
    }
    const t = cells[ti];
    const a = cells[ai];
    const tn = Number(t);
    const an = Number(a);
    if (!NUMBER.test(t) || !NUMBER.test(a) || !Number.isFinite(tn) || !Number.isFinite(an)) {
      throw new ClientError("invalid", notANumberMessage(row));
    }
    time_s.push(tn);
    absorbance.push(an);
  }
  if (time_s.length < MIN_READINGS) throw new ClientError("invalid", TOO_FEW_READINGS_MESSAGE);
  return { time_s, absorbance };
}

export const SAMPLE_READINGS: Readings = syntheticReadings({ k: 0.0085, a0: 0.8, a_end: 0.05, noise: 0.004, seed: 7 });
