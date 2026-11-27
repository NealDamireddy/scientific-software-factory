import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { builtinSkills } from "../app/extension-model.ts";

// Keep the portable entry points identical to the instructions sent by the UI.
const check = process.argv.includes("--check");
async function emit(target, content) {
  if (check) {
    if ((await readFile(target, "utf8")) !== content)
      throw new Error("Regenerate " + fileURLToPath(target));
  } else {
    await mkdir(new URL(".", target), { recursive: true });
    await writeFile(target, content);
  }
}

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
  await emit(target, body);
}

// Lab Factory deploys from its own package root. Bundle the editable skill
// records there so the hosted build does not need the reference app.
const hosted = builtinSkills.map((skill) => ({
  id: skill.id,
  title: skill.name,
  description: skill.description,
  body: [
    skill.whenToUse,
    "## Evidence to gather", skill.input,
    "## Review procedure", skill.instructions,
    "## Expected result", skill.output,
  ].join("\n\n"),
}));
await emit(
  new URL("../../lab-factory/web/lib/sample/research-skills.json", import.meta.url),
  JSON.stringify(hosted, null, 2) + "\n",
);
console.log(
  (check ? "Verified " : "Generated ") +
    builtinSkills.length +
    " portable skills and the hosted research catalog.",
);
