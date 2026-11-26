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

function cell(value: string | undefined): string {
  const trimmed = (value ?? "").trim();
  return trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"') ? trimmed.slice(1, -1).trim() : trimmed;
}

/**
 * Parses a readings CSV. Columns may come in any order; blank lines are skipped and do not count
 * as rows. Row numbers count the header as row 1. Throws ClientError("invalid") with the exact copy.
 */
export function parseReadingsCsv(text: string): Readings {
  const rows = text.replace(/^﻿/, "").split(/\r?\n|\r/).filter((line) => line.trim() !== "");
  const header = (rows[0] ?? "").split(",").map((name) => cell(name).toLowerCase());
  const ti = header.indexOf("time_s");
  const ai = header.indexOf("absorbance");
  if (ti < 0 || ai < 0) throw new ClientError("invalid", MISSING_COLUMNS_MESSAGE);
  const time_s: number[] = [];
  const absorbance: number[] = [];
  rows.slice(1).forEach((line, index) => {
    const cells = line.split(",");
    const t = cell(cells[ti]);
    const a = cell(cells[ai]);
    if (!NUMBER.test(t) || !NUMBER.test(a)) throw new ClientError("invalid", notANumberMessage(index + 2));
    time_s.push(Number(t));
    absorbance.push(Number(a));
  });
  if (time_s.length < MIN_READINGS) throw new ClientError("invalid", TOO_FEW_READINGS_MESSAGE);
  return { time_s, absorbance };
}

export const SAMPLE_READINGS: Readings = syntheticReadings({ k: 0.0085, a0: 0.8, a_end: 0.05, noise: 0.004, seed: 7 });
