// Pure checks used by the browser replay worker (replay.mjs).
// Kept separate so tests can import them without Pyodide.

export async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, "0")).join("");
}

/** Throws unless the fetched file matches its manifest entry. */
export function checkManifest(name, digest, manifest) {
  const entry = manifest?.[name];
  if (!entry || typeof entry.sha256 !== "string") throw Error(name + " is missing from the evidence manifest");
  if (digest !== entry.sha256) throw Error(name + " failed its integrity check");
}

/** Throws unless analysis.py is the exact source revision the factory verified. */
export function checkSourceRevision(digest, sourceRevision) {
  if (!sourceRevision) throw Error("The report records no source revision, so there is no verified source to replay");
  if (digest !== sourceRevision) throw Error("analysis.py does not match the verified source revision " + sourceRevision.slice(0, 12));
}

const within = (actual, expected, tolerance) =>
  typeof actual === "number" && Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;

/** True only when the reference case has metrics and every metric is within tolerance. */
export function metricsPass(reference, output) {
  const metrics = reference?.metrics;
  if (!Array.isArray(metrics) || metrics.length === 0) return false;
  return metrics.every(({field, expected, tolerance}) => {
    const actual = output?.[field];
    return Array.isArray(expected)
      ? Array.isArray(actual) && actual.length === expected.length && expected.every((n, i) => within(actual[i], n, tolerance))
      : within(actual, expected, tolerance);
  });
}

/** Plain statement of how much of the factory's suite the browser replayed. */
export function replayScope(replayed, total) {
  return "Replayed " + replayed + " of " + total + " reference case" + (total === 1 ? "" : "s") + " from the factory suite.";
}
