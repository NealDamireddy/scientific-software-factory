// Axis ticks on 1, 2 or 5 × 10ⁿ steps that cover [min, max].
// `count` is the target number of intervals; the result may have a few
// more or fewer ticks so that every tick is a round number.
export function niceTicks(min: number, max: number, count: number = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const low = Math.min(min, max);
  const high = Math.max(min, max);
  const intervals = Math.max(1, Math.floor(count) || 1);

  const rough = (high - low) / intervals;
  let exponent = Math.floor(Math.log10(rough));
  const fraction = rough / 10 ** exponent;
  // The small tolerance keeps values like 0.75 / 5 (1.4999999999999998 × 10⁻¹)
  // on the step a person would pick.
  const tolerance = 1e-9;
  let multiplier: number;
  if (fraction < 1.5 - tolerance) multiplier = 1;
  else if (fraction < 3 - tolerance) multiplier = 2;
  else if (fraction < 7 - tolerance) multiplier = 5;
  else {
    multiplier = 1;
    exponent += 1;
  }

  // Ticks are whole multiples of the step. Scaling by a power of ten with a
  // single multiply or divide avoids results like 0.6000000000000001.
  const scale = 10 ** Math.abs(exponent);
  const at = (index: number): number =>
    exponent >= 0 ? index * multiplier * scale : (index * multiplier) / scale;
  const step = at(1);
  const first = Math.floor(low / step + tolerance);
  const last = Math.ceil(high / step - tolerance);
  const ticks: number[] = [];
  for (let index = first; index <= last; index += 1) ticks.push(at(index));
  return ticks;
}
