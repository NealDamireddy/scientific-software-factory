// Where a value sits in its allowed range, as a fraction from 0 to 1.
// Used only to place a marker; it never decides whether a value passes.
export function markerPosition(value: number, minimum: number, maximum: number): number {
  if (Number.isNaN(value) || Number.isNaN(minimum) || Number.isNaN(maximum)) return 0;
  if (maximum === minimum) return 0.5;
  const fraction = (value - minimum) / (maximum - minimum);
  if (Number.isNaN(fraction)) return 0;
  return Math.min(1, Math.max(0, fraction));
}
