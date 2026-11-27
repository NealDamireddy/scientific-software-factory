import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { builtinSkills } from "../app/extension-model.ts";

// Keep the portable entry points identical to the instructions sent by the UI.
const check = process.argv.includes("--check");
for (const skill of builtinSkills) {
  const name = "research-" + skill.id;
  const dir = new URL("../skills/" + name + "/", import.meta.url);
  const target = new URL("SKILL.md", dir);
  const body = [
    "---",
    "name: " + name,
    "description: " + JSON.stringify(skill.description + " " + skill.whenToUse),
    "---",
    "",
    "# " + skill.name,
    "",
    "## Evidence to gather",
    "",
    skill.input.trim(),
    "",
    "## Review procedure",
    "",
    skill.instructions.trim(),
    "",
    "## Expected result",
    "",
    skill.output.trim(),
    "",
  ].join("\n");
  if (check) {
    if ((await readFile(target, "utf8")) !== body)
      throw new Error("Regenerate " + fileURLToPath(target));
  } else {
    await mkdir(dir, { recursive: true });
    await writeFile(target, body);
  }
}
console.log(
  (check ? "Verified " : "Generated ") +
    builtinSkills.length +
    " portable skills.",
);
