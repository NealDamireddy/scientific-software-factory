"""Run each independently authored candidate in its own Python process."""

import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
TRIALS = {
    "memory": ("lexical", "concept", "graph"),
    "review": ("transaction", "replay", "constraints"),
    "author": ("templates", "compiler", "synthesis"),
    "verify": ("controls", "interval", "metamorphic"),
    "trace": ("trapezoid", "shape", "segments"),
    "plan": ("rules", "typed", "preflight"),
    "ops": ("leases", "journal", "outbox"),
    "draft": ("extract", "grammar", "evidence"),
    "access": ("roles", "capabilities", "policy"),
    "storage": ("snapshot", "database", "objects"),
}


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def evaluate(area, approach, author_field_map=False):
    with contextlib.redirect_stdout(sys.stderr):
        candidate = load_file("trial_candidate", ROOT / "candidates" / area / approach / "candidate.py")
        grader = load_file("trial_grader", ROOT / "graders" / (area + ".py"))
        solve = candidate.solve
        if author_field_map:
            def solve(request):
                # Diagnostic only: keep identical field names and change their container.
                return candidate.solve({**request, "fields": {field: field for field in request["fields"]}})
        rows = list(grader.grade(solve))
    if not rows or len({name for name, _, _ in rows}) != len(rows):
        raise ValueError("The grader must return uniquely named cases")
    for name, passed, detail in rows:
        if not isinstance(name, str) or type(passed) is not bool or not isinstance(detail, str):
            raise ValueError("Expected (case name, boolean outcome, text detail)")
    return [{"case": name, "passed": passed, "detail": detail} for name, passed, detail in rows]


def trial(area, approach, author_field_map=False):
    command = [sys.executable, __file__, "--one", area, approach]
    if author_field_map:
        command.append("--author-field-map")
    try:
        result = subprocess.run(
            command, timeout=120,
            capture_output=True, text=True, check=True,
        )
        cases = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "Trial timed out after 120 seconds"}
    except subprocess.CalledProcessError as exc:
        return {"error": (exc.stderr.strip().splitlines() or ["Runner failed"])[-1]}
    candidate_path = ROOT / "candidates" / area / approach / "candidate.py"
    grader_path = ROOT / "graders" / (area + ".py")
    return {"passed": sum(row["passed"] for row in cases), "total": len(cases),
            "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            "grader_sha256": hashlib.sha256(grader_path.read_bytes()).hexdigest(), "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one", nargs=2, metavar=("AREA", "APPROACH"), help=argparse.SUPPRESS)
    parser.add_argument("--area", choices=TRIALS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--author-field-map", action="store_true",
                        help="Unscored author sensitivity: send field names as an identity mapping")
    args = parser.parse_args()
    if args.author_field_map:
        if args.area not in (None, "author") or (args.one and args.one[0] != "author"):
            parser.error("--author-field-map applies only to the author trial")
        args.area = "author"
    if args.one:
        area, approach = args.one
        if approach not in TRIALS.get(area, ()):
            parser.error("Unknown candidate")
        print(json.dumps(evaluate(area, approach, args.author_field_map), allow_nan=False))
        return
    results = {}
    for area, approaches in TRIALS.items():
        if args.area and args.area != area:
            continue
        results[area] = {}
        for approach in approaches:
            score = trial(area, approach, args.author_field_map)
            results[area][approach] = score
            if not args.json:
                summary = score["error"] if "error" in score else f"{score['passed']}/{score['total']}"
                print(f"{area:8s} {approach:13s} {summary}", flush=True)
                for case in score.get("cases", []):
                    if not case["passed"]:
                        print("  FAIL", case["case"], case["detail"])
    if args.json:
        print(json.dumps(results, indent=2, allow_nan=False))
    if any("error" in entry for group in results.values() for entry in group.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
