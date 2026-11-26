"use client";

import "./pages.css";

import { markerPosition } from "../lib/range.ts";
import type { CSSProperties } from "react";

export type RangeStripProps = {
  parameter: string;
  label: string;
  display: string;
  canonical: { value: number; unit: string; minimum: number; maximum: number };
};

const SPECTRUM_MIN = 400;
const SPECTRUM_MAX = 700;

/** For wavelength within the 400 to 700 nm spectrum, shows only the part the instrument covers; any other range gets the plain track. */
function trackStyle(parameter: string, unit: string, minimum: number, maximum: number): CSSProperties {
  if (parameter !== "wavelength" || unit !== "nm") return {};
  if (minimum < SPECTRUM_MIN || maximum > SPECTRUM_MAX) return {};
  const lo = Math.max(SPECTRUM_MIN, Math.min(SPECTRUM_MAX, minimum));
  const hi = Math.max(SPECTRUM_MIN, Math.min(SPECTRUM_MAX, maximum));
  const span = SPECTRUM_MAX - SPECTRUM_MIN;
  if (!(hi > lo)) return {};
  const width = (hi - lo) / span;
  const offset = width >= 1 ? 0 : (lo - SPECTRUM_MIN) / (span - (hi - lo));
  return {
    backgroundImage: "var(--spectrum)",
    backgroundRepeat: "no-repeat",
    backgroundSize: `${(100 / width).toFixed(3)}% 100%`,
    backgroundPosition: `${(offset * 100).toFixed(3)}% 0`,
  };
}

/** Shows where a value sits in the range an instrument allows. It never decides pass or fail. */
export function RangeStrip({ parameter, label, display, canonical }: RangeStripProps) {
  const { value, unit, minimum, maximum } = canonical;
  const percent = Number((markerPosition(value, minimum, maximum) * 100).toFixed(2));
  return (
    <div
      className="range-strip"
      role="img"
      aria-label={`${label} ${display}, allowed ${minimum} to ${maximum} ${unit}`}
    >
      <div className="range-head" aria-hidden="true">
        <span className="range-label">{label}</span>
        <span className="range-display">{display}</span>
      </div>
      <div className="range-track" aria-hidden="true" style={trackStyle(parameter, unit, minimum, maximum)}>
        <span className="range-marker" style={{ left: `${percent}%` }} />
      </div>
      <div className="range-ends" aria-hidden="true">
        <span>{minimum} {unit}</span>
        <span>{maximum} {unit}</span>
      </div>
    </div>
  );
}
