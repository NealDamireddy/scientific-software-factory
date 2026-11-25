// The instrument returns its own calculation with every run. Never show an
// application result that disagrees with it (same 1e-7 tolerances as the factory).
function close(actual, expected) {
  if (typeof actual !== "number" || !Number.isFinite(actual)) return false;
  return Math.abs(actual - expected) <= Math.max(1e-7 * Math.max(Math.abs(actual), Math.abs(expected)), 1e-7);
}

export function disagreement(output, reference) {
  if (!reference || typeof reference !== "object") return "The instrument did not return its reference result.";
  if (!output || typeof output !== "object") return "The application returned no result.";
  for (const [key, expected] of Object.entries(reference)) {
    const actual = output[key];
    const same = typeof expected === "number" ? close(actual, expected) : actual === expected;
    if (!same) return `The application's ${key} disagrees with the instrument's own calculation.`;
  }
  return null;
}

export function checkedReport(analysis, reference) {
  const problem = disagreement(analysis?.output, reference);
  if (problem) throw Error(problem + " The result was not shown.");
  return analysis;
}
