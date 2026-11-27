"""Run a single model/case cell through the backend. Use an empty output directory per comparison."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from starlette.testclient import TestClient
from labfactory.context import canonical_digest
from labfactory.hosted import application
from labfactory.store import Store
from labfactory.units import convert_exact
from labfactory.workorders import WorkOrders
from instrument_cases import CASES, request


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def model_path(tmp, arm, log):
    # Forward the real model's stdin, stdout, stderr and exit code. Keep only
    # the CLI's model metadata and stage name in the benchmark record.
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Codex CLI is required")
    flags = ["--model", "gpt-6-luna", "-c", 'model_reasoning_effort="low"'] if arm == "luna" else []
    path = Path(tmp)/"codex"
    path.write_text("""#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] != ["exec"]:
    sys.exit(2)
p = subprocess.run([BINARY, "exec", *FLAGS, *args[1:]], stderr=subprocess.PIPE)
text = p.stderr.decode(errors="replace")
def field(key):
    match = re.search(r"(?im)^" + key + r":\\s*([a-z0-9._-]+)", text)
    return match[1] if match else None
with open(LOG, "a") as f:
    print(json.dumps({"stage": Path.cwd().name.rsplit("-",1)[0], "model": field("model"),
                      "effort": field("reasoning effort"), "code": p.returncode}), file=f)
sys.stderr.buffer.write(p.stderr)
sys.exit(p.returncode)
""".replace("BINARY", repr(binary)).replace("FLAGS", repr(flags)).replace("LOG", repr(str(log))))
    path.chmod(0o700)
    os.environ["PATH"] = str(tmp) + os.pathsep + os.environ["PATH"]


def grade(case, result, phase):
    c = CASES[case]
    expected = c["expected"] if phase == "intake" else "in_review"
    if expected != "in_review":
        q = (result.get("question") or "").casefold()
        return {"correct_question": result["state"] == "needs_input" and result["input_kind"] == expected
                and all(any(t in q for t in group) for group in c["question_terms"]),
                "withheld_procedure": set(result["submission"]["artifact"]) == {"needs_input"}}
    if result["state"] != "in_review":
        return {"verified_draft": False}
    sub = result["submission"]
    steps = sub["artifact"]["steps"]
    text = " ".join(s["text"] for s in steps).lower()
    ops = [s for s in steps if s.get("action")]
    sources = {v for s in steps for v in s["citations"]}
    required = {c["guide"], "bench", "brief"}
    if phase == "answer":
        required.update(d["id"] for d in result["documents"] if d["title"] == "Study addendum")
    tests = {"backend_checks": sub["passed"] and all(r["passed"] for r in sub["results"]),
             "right_evidence": sources == required and (phase != "answer" or len(required) == 4),
             "manual_on_operation": any(c["guide"] in s["citations"] for s in ops),
             "instrument": bool(ops) and all(s["action"]["instrument_id"] == c["device"] and
                s["action"]["command"] in c["commands"] for s in ops)}
    if case == "balance":
        tests.update(tared="tare" in text, stable="stab" in text, compare=any(w in text for w in ("heavier", "larger reading", "larger mass", "greater mass", "higher mass")) and any(w in text for w in ("tie","equal")))
    elif case == "illuminance":
        tests.update(position="edge" in text, stable="stab" in text, compare=any(w in text for w in ("brighter","higher illuminance","higher lux","larger reading")) and any(w in text for w in ("tie","equal")))
    else:
        tests.update(interval=bool(ops) and all(len(s["action"]["settings"]) == 1 and
            s["action"]["settings"][0]["parameter"] == "interval" and convert_exact(
            s["action"]["settings"][0]["value"], s["action"]["settings"][0]["unit"], "min") == 2 for s in ops),
            range=bool(re.search(r"max(?:imum)?.*?(?:minus|[−–-]).*?min|subtract.*?min.*?from.*?max", text)),
            completeness=any(w in text for w in ("gap", "incomplete", "missing")),
            compare=any(w in text for w in ("smaller","narrower","lesser","lower")) and "tie" in text)
    return tests


def run(case, arm, root, operating_note=False):
    c = CASES[case]
    root.mkdir(parents=True, exist_ok=False)
    db = root/"lab.sqlite"
    os.environ.update(LABFACTORY_PUBLIC_REVIEW="1", LABFACTORY_AGENTS="{}", LABFACTORY_LOCAL_DB=str(db))
    receipts = []
    endpoint = "/api/procedure-drafts"
    body = request(case)
    if operating_note:
        if case != "temperature":
            raise ValueError("The operating-note comparison is specific to the logger.")
        bench = next(d for d in body["lab"]["documents"] if d["id"] == "bench")
        bench["text"] += ("\nIn this simulated bench, call record_temperature once per enclosure with the "
                          "project interval. The registered action starts and stops at the scheduled hold boundaries "
                          "and returns the completed, time-stamped trace labeled with its enclosure ID.")
    parent = None
    with tempfile.TemporaryDirectory() as tmp, TestClient(application, base_url="http://localhost",
            headers={"Origin":"http://localhost"}) as api:
        model_path(tmp, arm, root/"calls.jsonl")
        for phase in ("intake", "answer"):
            save(root/(phase+"-input.json"), body)
            for attempt in (1, 2):
                response = api.post(endpoint, json=body)
                result = response.json()
                save(root/f"{phase}-{attempt}.json", result)
                receipt = {"phase":phase, "attempt":attempt, "http":response.status_code, "state":result.get("state"),
                           "question":result.get("question"), "error":result.get("error"), "request_digest":canonical_digest(body)}
                receipts.append(receipt)
                if response.status_code != 503 or attempt == 2:
                    break
            if response.status_code != 201:
                break
            oid = result["order"]["id"]
            assert result == api.get("/api/procedure-drafts/"+oid).json()
            with Store(db) as store:
                orders = WorkOrders(store)
                sub = orders.submission(oid)
                assert canonical_digest(sub.artifact) == sub.artifact_digest
                assert tuple(orders._check(orders.get(oid), sub.artifact)) == sub.results
            if parent:
                assert result["previous_order"] == parent
            receipt["grading"] = grade(case, result, phase)
            receipt["checks"] = len(sub.results)
            if not all(receipt["grading"].values()) or result["state"] == "in_review" or phase == "answer":
                break
            parent = oid
            endpoint = f"/api/procedure-drafts/{oid}/answers"
            body = {"request_id":"reply","title":"Study addendum","text":c["answer"]}
    success = (receipts[-1]["state"] == "in_review" and all(receipts[-1].get("grading", {"missing":False}).values())
               and (c["expected"] == "in_review" or receipts[-1]["phase"] == "answer"))
    calls = [json.loads(line) for line in (root/"calls.jsonl").read_text().splitlines()]
    models = {r["model"] for r in calls}
    assert len(models) == 1 and None not in models and (arm != "luna" or models == {"gpt-6-luna"})
    summary = {"case":case,"arm":arm,"model":models.pop(),"efforts":sorted({r["effort"] for r in calls}),
               "receipts":receipts,"success":success}
    save(root/"summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES)
    parser.add_argument("arm", choices=["default","luna"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--operating-note", action="store_true")
    args = parser.parse_args()
    sys.exit(0 if run(args.case, args.arm, args.output.resolve()/args.case/args.arm, args.operating_note) else 1)
