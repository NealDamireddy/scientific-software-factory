// Numbers as the interface shows them: plain decimals, never exponent notation.

/**
 * Writes a finite number with `digits` significant figures, in plain decimals,
 * however big or small: the figures come from toExponential (which rounds, so 9.996 becomes 10.0)
 * and are then placed by hand, never left in exponent form.
 */
function significant(n: number, digits: number): string {
  if (n === 0) return "0";
  const [mantissa, exponent] = Math.abs(n).toExponential(digits - 1).split("e");
  const figures = mantissa.replace(".", "");
  const e = Number(exponent);
  let body: string;
  if (e >= figures.length - 1) body = figures + "0".repeat(e - figures.length + 1);
  else if (e >= 0) body = `${figures.slice(0, e + 1)}.${figures.slice(e + 1)}`;
  else body = `0.${"0".repeat(-e - 1)}${figures}`;
  return n < 0 ? `-${body}` : body;
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
