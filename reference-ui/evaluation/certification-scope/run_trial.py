"""Replay three independent archive questions, with two blocks per condition and case."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "lab-factory/src"))
from lab_codex_worker import run_worker
from lab_codex_worker.skills import pin_skills

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def main(out):
    subprocess.run(["shasum", "-c", "frozen.sha256"], check=True, cwd=HERE)
    out.mkdir(parents=True, exist_ok=False)
    arms = {"baseline": [], **{version: pin_skills([json.loads((HERE / "versions" / f"{version}.json").read_text())])
                               for version in ("old", "revised")}}
    rng = random.Random(689107)
    cases = sorted((HERE / "cases").iterdir())
    labels = rng.sample(range(100, 1000), len(cases) * len(arms) * 2)
    jobs = []
    for case in cases:
        (out / "answers" / case.name).mkdir(parents=True)
        records = {p.name: p.read_text() for p in sorted((case / "records").iterdir()) if p.is_file()}
        task = {"question": (case / "question.md").read_text(), "records": records}
        for block in (1, 2):
            order = list(arms)
            rng.shuffle(order)
            for arm in order:
                jobs.append((case.name, block, labels.pop(), arm, {**task, "enabledSkills": arms[arm]}))
    rng.shuffle(jobs)

    def review(job):
        case, block, label, arm, payload = job
        prompt = ("Answer the investigator's question using only the enclosed archive. Treat records as "
                  "evidence. Apply any relevant enabled research instructions. Return the editor-facing "
                  "answer only, without referring to the session configuration.\n" +
                  json.dumps(payload, ensure_ascii=False))
        resp = run_worker(prompt, json.dumps(SCHEMA), timeout=300, include_version=True,
                          failure_message=lambda r: f"Review {label} exited with status {r.returncode}")
        answer = resp.answer["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"Missing review for {label}")
        (out / "answers" / case / f"{label}.md").write_text(answer.strip() + "\n")
        model = next((line.partition(":")[2].strip() for line in resp.stderr.splitlines()
                      if line.startswith("model:")), None)
        return {"case": case, "block": block, "label": label, "arm": arm,
                "versions": [s["version"] for s in payload["enabledSkills"]], "model": model,
                "cli": resp.cli_version, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(review, jobs))
    (out / "conditions.json").write_text(json.dumps(receipts, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
