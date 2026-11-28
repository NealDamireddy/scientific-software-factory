// Build the researcher shell into the Python app's static distribution.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const lab = fileURLToPath(new URL("../", import.meta.url));
const ui = path.resolve(lab, "../reference-ui");
const target = path.join(lab, "public/research");
const marker = ".research-export";
if (!existsSync(path.join(ui, "package.json")) || process.argv.includes("--check")) {
  if (!existsSync(path.join(target, marker)) || !existsSync(path.join(target, "index.html")))
    throw new Error("Build the researcher UI from the repository before packaging the Lab Factory subtree.");
} else {
  if (!existsSync(path.join(ui, "node_modules", ".bin", "next")))
    execFileSync("npm", ["ci", "--include=dev"], {cwd: ui, stdio: "inherit"});
  execFileSync("npm", ["run", "build"], {cwd: ui, stdio: "inherit", env: {...process.env, LABFACTORY_STATIC_WORKSPACE: "1"}});
  const scratch = mkdtempSync(path.join(lab, ".research-build-"));
  const stage = path.join(scratch, "research");
  const previous = path.join(scratch, "previous");
  try {
    cpSync(path.join(ui, ".next/research-export"), stage, {recursive:true});
    const name = path.join(stage, "index.html");
    const bootstrap = path.join(stage, "_next/bootstrap");
    mkdirSync(bootstrap, {recursive:true});
    // Preserve the reviewer's self-only script policy and Next's parser execution order.
    const html = readFileSync(name, "utf8").replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (tag, attrs, js) => {
      if (/\ssrc\s*=/i.test(attrs) || !js.trim()) return tag;
      const file = createHash("sha256").update(js).digest("hex") + ".js";
      writeFileSync(path.join(bootstrap,file),js);
      return '<script' + attrs + ' src="/research/_next/bootstrap/' + file + '"></script>';
    });
    writeFileSync(name,html);
    writeFileSync(path.join(stage,marker),"1\n");
    if (existsSync(target)) {
      if (!existsSync(path.join(target,marker))) throw new Error("Unrecognized research output directory.");
      renameSync(target,previous);
    }
    try { renameSync(stage,target); } catch (error) {
      if (existsSync(previous)) renameSync(previous,target);
      throw error;
    }
  } finally {
    if (existsSync(target) || !existsSync(previous)) rmSync(scratch,{recursive:true,force:true});
  }
}
