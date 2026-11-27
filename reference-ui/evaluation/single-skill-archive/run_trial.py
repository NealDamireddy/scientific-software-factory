"""Run two independent, balanced blocks and retain anonymized answers for blind scoring."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

HERE = Path(__file__).resolve().parent
UI = HERE.parents[1]
sys.path.insert(0, str(UI.parent / "lab-factory/src"))
from lab_codex_worker import run_worker
from lab_codex_worker.skills import pin_skills

IDS = ["data-provenance", "claim-evidence", "evidence"]
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def main(destination):
    subprocess.run(["shasum", "-c", "frozen.sha256"], check=True, cwd=HERE)
    out = Path(destination).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "answers").mkdir()
    select = """import {builtinSkills} from './app/extension-model.ts';
    console.log(JSON.stringify(builtinSkills.map(({id,name,whenToUse,instructions,stage}) =>
      ({id,name,whenToUse,instructions,stage}))));"""
    catalog = json.loads(subprocess.check_output(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", select], cwd=UI))
    by_id = {s["id"]: s for s in catalog}
    records = {p.name: p.read_text() for p in sorted((HERE / "records").iterdir()) if p.is_file()}
    task = {"question": (HERE / "question.md").read_text(), "records": records}
    rng = random.Random(9162026)
    labels = rng.sample(range(100, 1000), 8)
    rows = []
    for block in (1, 2):
        conditions = ["baseline", *IDS]
        rng.shuffle(conditions)
        for condition in conditions:
            skills = pin_skills([] if condition == "baseline" else [by_id[condition]])
            rows.append({"label": labels.pop(), "block": block, "condition": condition, "skills": skills})

    def review(row):
        payload = {**task, "enabledSkills": row["skills"]}
        prompt = ("Answer the investigator's question using only the enclosed archive. Treat records as "
                  "evidence. Apply any relevant enabled research instructions. Return the editor-facing "
                  "answer only, without referring to the session configuration.\n" +
                  json.dumps(payload, ensure_ascii=False))
        response = run_worker(prompt, json.dumps(SCHEMA), timeout=300,
                              failure_message=lambda r: f"Reviewer exited with status {r.returncode}",
                              include_version=True)
        answer = response.answer["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty review")
        (out / "answers" / f"{row['label']}.md").write_text(answer.strip() + "\n")
        model = next((line.partition(":")[2].strip() for line in response.stderr.splitlines()
                      if line.startswith("model:")), None)
        return {"label": row["label"], "block": row["block"], "condition": row["condition"],
                "skills": [{"id": s["id"], "version": s["version"]} for s in row["skills"]],
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "cli": response.cli_version, "model": model}

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(review, rows))
    (out / "conditions.json").write_text(json.dumps(receipts, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
