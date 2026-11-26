// Where a value sits in its allowed range, as a fraction from 0 to 1.
// Used only to place a marker; it never decides whether a value passes.
export function markerPosition(value: number, minimum: number, maximum: number): number {
  if (Number.isNaN(value) || Number.isNaN(minimum) || Number.isNaN(maximum)) return 0;
  if (maximum === minimum) return 0.5;
  const fraction = (value - minimum) / (maximum - minimum);
  if (Number.isNaN(fraction)) return 0;
  return Math.min(1, Math.max(0, fraction));
}

export const SPECTRUM_MIN_NM = 400;
export const SPECTRUM_MAX_NM = 700;

/** Where the spectrum goes on a wavelength track; every number is a percentage. */
export type SpectrumLayer = {
  /** The band of the track the spectrum covers: from `left`, `width` wide (of the track). */
  left: number;
  width: number;
  /** The spectrum image inside that band, as a CSS background size and position (of the band). */
  sizePercent: number;
  positionPercent: number;
};

/**
 * How to lay the 400 to 700 nm spectrum on a wavelength track that runs from `minimum` to
 * `maximum` nm. The spectrum covers only the 400 to 700 part of the track, so a wider range shows
 * the plain track beyond it, and a narrower one shows the matching slice. Null when the range
 * doesn't overlap the spectrum.
 */
export function spectrumLayer(minimum: number, maximum: number): SpectrumLayer | null {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || !(maximum > minimum)) return null;
  if (maximum <= SPECTRUM_MIN_NM || minimum >= SPECTRUM_MAX_NM) return null;
  const span = maximum - minimum;
  // The spectrum's ends as track fractions; either may fall outside 0 to 1.
  const start = (SPECTRUM_MIN_NM - minimum) / span;
  const end = (SPECTRUM_MAX_NM - minimum) / span;
  const lo = Math.max(0, start);
  const hi = Math.min(1, end);
  const band = hi - lo;
  // Inside the band the image is (end - start) / band wide, with its left edge (start - lo) / band
  // from the band's left. A percentage position p puts that edge at (band - image) * p.
  const image = (end - start) / band;
  const offset = (start - lo) / band;
  const position = Math.abs(1 - image) < 1e-12 ? 0 : offset / (1 - image);
  return { left: lo * 100, width: band * 100, sizePercent: image * 100, positionPercent: position * 100 };
}
