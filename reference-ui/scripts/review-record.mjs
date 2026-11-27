// Read-only entry point for coding agents and local analysis pipelines.
import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { basename } from "node:path";
import { parseRecordCsv, maxFileBytes } from "../app/record-csv.ts";
import { reviewEvidencePacket } from "../app/review-skills/evidence.ts";

const usage =
  "Usage: node scripts/review-record.mjs observations.csv [--claim claim.json]";
async function readInput(path) {
  const info = await stat(path);
  if (!info.isFile() || info.size > maxFileBytes)
    throw new Error("Input must be a regular file of at most 1 MiB.");
  const data = await readFile(path);
  if (data.length > maxFileBytes)
    throw new Error("File exceeds the input limit.");
  return data;
}
async function main() {
  const [input, flag, claimPath, ...extra] = process.argv.slice(2);
  if (input === "--help") {
    console.log(usage);
    return;
  }
  if (
    !input ||
    extra.length ||
    (flag !== undefined && (flag !== "--claim" || !claimPath))
  )
    throw new Error(usage);
  const data = await readInput(input);
  const sourceCsv = new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: true,
  }).decode(data);
  const packet = {
    source: basename(input),
    observations: parseRecordCsv(sourceCsv),
  };
  if (claimPath) {
    const claim = JSON.parse((await readInput(claimPath)).toString("utf8"));
    if (
      !claim ||
      !["sample", "measurement", "unit"].every(
        (k) => typeof claim[k] === "string" && claim[k].trim(),
      ) ||
      !Number.isFinite(claim.value)
    )
      throw new Error(
        "Claim JSON requires sample, measurement, unit and a finite numeric value.",
      );
    if (claim.statistic !== undefined && claim.statistic !== "mean")
      throw new Error("The supported aggregate statistic is mean.");
    const { sample, measurement, value, unit, statistic } = claim;
    packet.claim = {
      sample,
      measurement,
      value,
      unit,
      ...(statistic ? { statistic } : {}),
    };
  }
  const skills = claimPath
    ? ["data-provenance", "claim-evidence"]
    : ["data-provenance"];
  const report = {
    schemaVersion: 1,
    scope: "local-read-only-record-review",
    selectedSkills: skills,
    sourceCsv,
    sourceSha256: createHash("sha256").update(data).digest("hex"),
    packet,
    findings: reviewEvidencePacket(packet, skills),
  };
  console.log(JSON.stringify(report, null, 2));
}
main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
