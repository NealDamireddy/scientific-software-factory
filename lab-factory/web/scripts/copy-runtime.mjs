// Copies the Pyodide files the app needs into public/runtime/, so the Python
// runtime is served from this origin and works offline.
import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const target = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "runtime");
const files = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip"];

await mkdir(target, { recursive: true });
for (const file of files) {
  await copyFile(require.resolve(`pyodide/${file}`), join(target, file));
}
