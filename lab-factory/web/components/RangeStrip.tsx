"use client";

import "./pages.css";

import { markerPosition, spectrumLayer } from "../lib/range.ts";
import type { CSSProperties } from "react";

export type RangeStripProps = {
  parameter: string;
  label: string;
  display: string;
  canonical: { value?: number; unit: string; minimum: number; maximum: number };
};

/**
 * A wavelength track shows the spectrum over the part of its range that lies within 400 to 700 nm,
 * and the plain track elsewhere; any other parameter gets the plain track.
 */
function spectrumStyle(parameter: string, unit: string, minimum: number, maximum: number): CSSProperties | null {
  if (parameter !== "wavelength" || unit !== "nm") return null;
  const layer = spectrumLayer(minimum, maximum);
  if (!layer) return null;
  const f = (n: number) => `${Number(n.toFixed(3))}%`;
  // Round only the ends that meet the track's own rounded ends.
  const leftEnd = layer.left <= 0.001;
  const rightEnd = layer.left + layer.width >= 99.999;
  return {
    left: f(layer.left),
    width: f(layer.width),
    backgroundSize: `${f(layer.sizePercent)} 100%`,
    backgroundPosition: `${f(layer.positionPercent)} 0`,
    borderRadius: `${leftEnd ? 4 : 0}px ${rightEnd ? 4 : 0}px ${rightEnd ? 4 : 0}px ${leftEnd ? 4 : 0}px`,
  };
}

/** Shows where a value sits in the range an instrument allows. It never decides pass or fail. */
export function RangeStrip({ parameter, label, display, canonical }: RangeStripProps) {
  const { value, unit, minimum, maximum } = canonical;
  const percent = value === undefined ? null : Number((markerPosition(value, minimum, maximum) * 100).toFixed(2));
  const spectrum = spectrumStyle(parameter, unit, minimum, maximum);
  return (
    <div
      className="range-strip"
      role="img"
      aria-label={value === undefined ? `${label}, allowed ${minimum} to ${maximum} ${unit}` : `${label} ${display}, allowed ${minimum} to ${maximum} ${unit}`}
    >
      <div className="range-head" aria-hidden="true">
        <span className="range-label">{label}</span>
        <span className="range-display">{display}</span>
      </div>
      <div className="range-track" aria-hidden="true">
        {spectrum && <span className="range-spectrum" style={spectrum} />}
        {percent !== null && <span className="range-marker" style={{ left: `${percent}%` }} />}
      </div>
      <div className="range-ends" aria-hidden="true">
        <span>{minimum} {unit}</span>
        <span>{maximum} {unit}</span>
      </div>
    </div>
  );
}
