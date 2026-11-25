import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
await mkdir("public/runtime", { recursive: true });
for (const file of ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip"]) {
  await copyFile(require.resolve("pyodide/" + file), "public/runtime/" + file);
}
const licenseInfo = await readFile("docs/NOTICE.md", "utf8");
await writeFile("public/runtime/NOTICE.txt", licenseInfo);
await copyFile("factory/optics.py", "public/runtime/optics.py");
await copyFile("LICENSE", "public/runtime/instrument-license.txt");
