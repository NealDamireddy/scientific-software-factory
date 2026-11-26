"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";

import { plainNumber } from "../lib/format.ts";
import { dataRows, linearScale, plotAxes, seriesSummary, tickLabel } from "../lib/plot.ts";
import type { PlotSeries } from "../lib/plot.ts";

export type PlotProps = { title: string; xLabel: string; yLabel: string; series: PlotSeries[] };

// Lines differ by dash as well as colour, so the legend never depends on colour alone.
const DASHES = [undefined, "7 4", "2 3", "9 3 2 3"];
const HEIGHT = 300;
const MARGIN = { top: 14, right: 18, bottom: 50, left: 62 };
const DEFAULT_WIDTH = 600;
const MIN_WIDTH = 300;

function colour(index: number): string {
  return `var(--plot-${(index % 4) + 1})`;
}

/** Each line series' dash, counted among the lines only, so the first line is always solid. */
function dashes(series: PlotSeries[]): (string | undefined)[] {
  let line = 0;
  return series.map((s) => (s.style === "line" ? DASHES[line++ % DASHES.length] : undefined));
}

function Swatch({ style, index, dash }: { style: PlotSeries["style"]; index: number; dash: string | undefined }) {
  return (
    <svg className="plot-swatch" width="24" height="12" viewBox="0 0 24 12" aria-hidden="true">
      {style === "points" ? (
        <>
          <circle cx="6" cy="6" r="2.75" fill={colour(index)} />
          <circle cx="18" cy="6" r="2.75" fill={colour(index)} />
        </>
      ) : (
        <line x1="1" y1="6" x2="23" y2="6" stroke={colour(index)} strokeWidth="2.25" strokeDasharray={dash} />
      )}
    </svg>
  );
}

/**
 * An SVG plot of points and lines on nice-tick axes, with a legend, a summary for screen readers and
 * a `Show data` table. It takes its container's width, so text stays at its size in a narrow panel.
 */
export function Plot({ title, xLabel, yLabel, series }: PlotProps) {
  const uid = useId();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [showData, setShowData] = useState(false);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(MIN_WIDTH, Math.round(el.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const axes = plotAxes(series);
  const left = MARGIN.left;
  const right = width - MARGIN.right;
  const top = MARGIN.top;
  const bottom = HEIGHT - MARGIN.bottom;
  const x = linearScale(axes.x.domain, [left, right]);
  const y = linearScale(axes.y.domain, [bottom, top]);
  const rows = dataRows(series);
  const dash = dashes(series);
  // Lines first, then points on top, so every reading stays visible.
  const order = series.map((s, i) => ({ s, i })).sort((a, b) => Number(a.s.style === "points") - Number(b.s.style === "points"));

  return (
    <figure className="plot" aria-labelledby={`${uid}-title`}>
      <figcaption id={`${uid}-title`} className="plot-title">{title}</figcaption>
      <ul className="plot-legend" aria-label="Legend">
        {series.map((s, i) => (
          <li key={`${s.label}-${i}`} className="plot-legend-item">
            <Swatch style={s.style} index={i} dash={dash[i]} />
            <span>{s.label}</span>
          </li>
        ))}
      </ul>
      <div ref={box} className="plot-box">
        <svg
          className="plot-svg"
          role="img"
          aria-label={seriesSummary(title, series)}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          width="100%"
          preserveAspectRatio="xMidYMid meet"
        >
          <g className="plot-grid">
            {axes.y.ticks.map((t) => <line key={`gy${t}`} x1={left} x2={right} y1={y(t)} y2={y(t)} />)}
            {axes.x.ticks.map((t) => <line key={`gx${t}`} x1={x(t)} x2={x(t)} y1={top} y2={bottom} />)}
          </g>
          <g className="plot-ticks">
            {axes.y.ticks.map((t) => (
              <text key={`ty${t}`} x={left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">{tickLabel(t, axes.y.ticks)}</text>
            ))}
            {axes.x.ticks.map((t) => (
              <text key={`tx${t}`} x={x(t)} y={bottom + 18} textAnchor="middle">{tickLabel(t, axes.x.ticks)}</text>
            ))}
          </g>
          <line className="plot-axis" x1={left} x2={right} y1={bottom} y2={bottom} />
          <line className="plot-axis" x1={left} x2={left} y1={top} y2={bottom} />
          <text className="plot-axis-label" x={(left + right) / 2} y={HEIGHT - 8} textAnchor="middle">{xLabel}</text>
          <text
            className="plot-axis-label"
            x={0}
            y={0}
            transform={`translate(16 ${(top + bottom) / 2}) rotate(-90)`}
            textAnchor="middle"
          >
            {yLabel}
          </text>
          {order.map(({ s, i }) => s.style === "line" ? (
            <polyline
              key={`s${i}`}
              className="plot-line"
              points={s.points.map(([px, py]) => `${x(px).toFixed(2)},${y(py).toFixed(2)}`).join(" ")}
              stroke={colour(i)}
              strokeDasharray={dash[i]}
            />
          ) : (
            <g key={`s${i}`} className="plot-points" fill={colour(i)}>
              {s.points.map(([px, py], j) => <circle key={j} cx={x(px)} cy={y(py)} r="3" />)}
            </g>
          ))}
        </svg>
      </div>
      <button
        type="button"
        className="ws-button plot-toggle"
        aria-expanded={showData}
        aria-controls={`${uid}-data`}
        onClick={() => setShowData((open) => !open)}
      >
        Show data
      </button>
      <div id={`${uid}-data`} className="plot-data" hidden={!showData} role="region" tabIndex={showData ? 0 : -1} aria-label={`${title} data`}>
        {showData && (
          <table className="plot-table">
            <caption>{title}</caption>
            <thead>
              <tr>
                <th scope="col">{xLabel}</th>
                {series.map((s, i) => <th key={i} scope="col">{s.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.x}>
                  <th scope="row">{plainNumber(row.x)}</th>
                  {row.values.map((v, i) => <td key={i}>{v === null ? "" : plainNumber(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </figure>
  );
}
