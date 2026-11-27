// Stage EVOLVE's production export for the reviewer portal. A deployment of the
// Lab Factory subtree alone can verify the prebuilt distribution without npm.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync,
  readdirSync, renameSync, rmSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const lab = fileURLToPath(new URL("../", import.meta.url));
const root = path.resolve(lab, "..");
const output = path.join(root, ".next/evolve-export");
const destination = path.join(lab, "public", "evolve");
const manifestFile = "build-manifest.json";
const pages = ["index.html", "b12/index.html", "workspace/index.html"];
const runtime = [
  "NOTICE.txt", "pyodide-lock.json", "pyodide.mjs", "pyodide.asm.mjs",
  "pyodide.asm.wasm", "python_stdlib.zip",
];
const required = [...pages, "replay.mjs", ...runtime.map(name => "runtime/" + name),
  "b12/completed.json", ...["registration", "report", "predictions"].map(name => "b12/evaluation/" + name + ".json")];
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");

function files(dir, prefix = "") {
  const result = [];
  for (const item of readdirSync(path.join(dir, prefix), {withFileTypes: true})) {
    const relative = path.posix.join(prefix, item.name);
    if (item.isDirectory()) result.push(...files(dir, relative));
    else if (item.isFile()) result.push(relative);
    else throw new Error("Unexpected non-regular file: " + relative);
  }
  return result.sort();
}

function inventory(dir) {
  return Object.fromEntries(files(dir).filter(file => file !== manifestFile)
    .map(file => [file, sha256(readFileSync(path.join(dir, file)))]));
}

function readManifest(dir) {
  const manifest = JSON.parse(readFileSync(path.join(dir, manifestFile), "utf8"));
  if (manifest.format !== 1 || typeof manifest.files !== "object" || !manifest.files)
    throw new Error("Invalid EVOLVE build manifest: " + dir);
  for (const file of required) {
    if (!manifest.files[file]) throw new Error("Missing EVOLVE asset: " + file);
  }
  for (const project of ["curie", "linewidth"]) {
    if (!Object.keys(manifest.files).some(file => file.startsWith("evidence/" + project + "/") && file.endsWith("/analysis.py")))
      throw new Error("Missing verified EPR replay for " + project);
  }
  return manifest;
}

function verify(dir) {
  if (JSON.stringify(readManifest(dir).files) !== JSON.stringify(inventory(dir)))
    throw new Error("The staged EVOLVE export contains missing, changed or unexpected files: " + dir);
}

function checkOwned(dir) {
  const manifest = readManifest(dir);
  for (const file of files(dir)) {
    if (file !== manifestFile && !Object.hasOwn(manifest.files, file))
      throw new Error("Cannot replace an unrecognized file in the export: " + path.join(dir, file));
  }
}

// Next emits parser-ordered inline Flight scripts. Keep their order, and serve
// their exact JavaScript bytes as same-origin assets under the existing CSP.
function stagePage(file, stage) {
  const html = readFileSync(path.join(output, file), "utf8");
  if (!html.includes('src="/evolve/_next/'))
    throw new Error("Expected a Next.js export built for /evolve in " + file);
  const result = html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (tag, attrs, code) => {
    if (/\ssrc\s*=/i.test(attrs) || !code.trim()) return tag;
    const url = "_next/bootstrap/" + sha256(code) + ".js";
    writeFileSync(path.join(stage, url), code);
    return '<script' + attrs + ' src="/evolve/' + url + '"></script>';
  });
  mkdirSync(path.dirname(path.join(stage, file)), {recursive: true});
  writeFileSync(path.join(stage, file), result);
}

function stageExport(stage) {
  function copy(file) {
    cpSync(path.join(output, file), path.join(stage, file), {recursive: true});
  }
  copy("_next");
  mkdirSync(path.join(stage, "_next/bootstrap"), {recursive: true});
  for (const page of pages) {
    stagePage(page, stage);
    const dir = path.dirname(page);
    for (const name of readdirSync(path.join(output, dir))) {
      if (/^(?:index|__next\.[\w.]+)\.txt$/.test(name)) copy(path.join(dir, name));
    }
  }
  for (const file of required.filter(name => !pages.includes(name))) copy(file);
  for (const project of ["curie", "linewidth"]) {
    const folder = path.join("evidence", project);
    for (const run of readdirSync(path.join(output, folder))) {
      if (!/^\d{8}T\d{6}Z-[a-f\d]+$/.test(run)) continue;
      const dir = path.join(folder, run);
      const report = JSON.parse(readFileSync(path.join(output, dir, "report.json"), "utf8"));
      copy(path.join(dir, "report.json"));
      for (const [file, artifact] of Object.entries(report.artifacts)) {
        if (path.basename(file) !== file || !/\.(?:json|txt|csv|py|lock)$/.test(file))
          throw new Error("Unexpected EPR evidence file in " + dir + ": " + file);
        if (sha256(readFileSync(path.join(output, dir, file))) !== artifact.sha256)
          throw new Error("EPR evidence does not match the report: " + path.join(dir, file));
        copy(path.join(dir, file));
      }
    }
  }
  writeFileSync(path.join(stage, manifestFile), JSON.stringify({format: 1, files: inventory(stage)}, null, 2) + "\n");
  verify(stage);
}

function build() {
  const hasSources = existsSync(path.join(root, "next.config.mjs")) && existsSync(path.join(root, "app/page.jsx"));
  if (!hasSources || process.argv.includes("--check")) {
    if (!existsSync(path.join(destination, manifestFile)))
      throw new Error("Missing EVOLVE export. Run npm run build:lab from the repository root before uploading lab-factory, or enable source files outside the Vercel project root for Git builds.");
    verify(destination);
    console.log("Verified staged EVOLVE pages, evidence, and runtime.");
    return;
  }
  if (!existsSync(path.join(root, "node_modules", ".bin", "next")))
    execFileSync("npm", ["ci", "--include=dev"], {cwd: root, stdio: "inherit"});
  execFileSync("npm", ["run", "build"], {cwd: root, stdio: "inherit", env: {...process.env, EVOLVE_BASE_PATH: "/evolve"}});

  const temp = mkdtempSync(path.join(lab, ".portal-build-"));
  const stage = path.join(temp, "evolve");
  const previous = path.join(temp, "previous");
  let published = false;
  try {
    stageExport(stage);
    if (existsSync(destination)) {
      if (!lstatSync(destination).isDirectory()) throw new Error("Cannot replace " + destination);
      checkOwned(destination);
      renameSync(destination, previous);
    }
    try {
      renameSync(stage, destination);
      published = true;
    }
    catch (error) {
      if (existsSync(previous)) renameSync(previous, destination);
      throw error;
    }
  } finally {
    if (published || !existsSync(previous)) rmSync(temp, {recursive: true, force: true});
  }
  console.log("Built Lab Factory at " + path.join(lab, "public"));
}

build();
