// Numbers as the interface shows them: plain decimals, never exponent notation.

/** Writes a finite number with `digits` significant figures, in plain decimals. */
function significant(n: number, digits: number): string {
  if (n === 0) return "0";
  // Round first, so 9.996 becomes 10.0 rather than 9.996 written to 3 decimals.
  const rounded = Number(n.toPrecision(digits));
  if (rounded === 0) return "0";
  const magnitude = Math.floor(Math.log10(Math.abs(rounded)));
  const decimals = digits - 1 - magnitude;
  if (decimals >= 0) return rounded.toFixed(Math.min(decimals, 100));
  const step = 10 ** -decimals;
  return String(Math.round(rounded / step) * step);
}

/** 3 significant figures as a plain decimal, keeping trailing zeros: `0.00851`, `81.4`, `0.0100`. */
export function sig3(n: number): string {
  if (!Number.isFinite(n)) return "not a number";
  return significant(n, 3);
}

/** Up to 4 significant figures, trailing zeros dropped: `0.8012`, `0.05`, `600`. For data tables. */
export function plainNumber(n: number): string {
  if (!Number.isFinite(n)) return "not a number";
  const text = significant(n, 4);
  return text.includes(".") ? text.replace(/\.?0+$/, "") : text;
}
