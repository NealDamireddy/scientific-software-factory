"""Replay the signed-in Mac author's saved responses. Use --collect for live generation."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from graders import author
from labfactory.tabular_analysis import INSTRUCTIONS
from labfactory import tabular_worker


EVIDENCE = Path(__file__).resolve().parent / "evidence" / "author_baseline.json"


def context(request):
    return {"instructions": INSTRUCTIONS,
            "analysis": {key: request[key] for key in ("protocol", "fields", "unit")}}


def input_hash(payload):
    material = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(material).hexdigest()


def inputs():
    # The grader provides the public request to its candidate callback. Its
    # private labels, observations and numerical answers never reach the author.
    requests = {}

    def capture(request):
        payload = context(request)
        requests[input_hash(payload)] = payload
        return {"needs_input": "Input inventory only"}

    author.grade(capture)
    return requests


def generate(item, cli_version, driver_hash):
    key, payload = item
    start = time.monotonic()
    attempt = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "cli_version": cli_version,
        "driver_sha256": driver_hash,
    }
    try:
        attempt["artifact"] = tabular_worker.generate(payload)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        attempt["infrastructure_error"] = f"{type(exc).__name__}: {exc}"
    attempt["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return key, attempt


def save(evidence):
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    pending = EVIDENCE.with_suffix(".json.tmp")
    pending.write_text(json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    pending.replace(EVIDENCE)


def collect(evidence, requests, limit, fresh):
    cli_version = subprocess.run(["codex", "--version"], capture_output=True,
                                 check=True, text=True).stdout.strip()
    driver_hash = hashlib.sha256(Path(tabular_worker.__file__).read_bytes()).hexdigest()
    pending = [(key, payload) for key, payload in requests.items()
               if fresh or "artifact" not in evidence["attempts"].get(key, [{}])[-1]]
    if limit is not None:
        pending = pending[:limit]
    print(f"Live collection: {len(pending)} queued; {len(requests)} total inputs.", flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index in range(0, len(pending), 2):
            futures = [pool.submit(generate, item, cli_version, driver_hash)
                       for item in pending[index:index+2]]
            batch_failed = False
            for future in futures:
                key, attempt = future.result()
                evidence["attempts"].setdefault(key, []).append(attempt)
                error = attempt.get("infrastructure_error")
                print(f"{key[:12]}: {error or 'fresh artifact'} ({attempt['elapsed_seconds']}s)", flush=True)
                batch_failed |= error is not None
                save(evidence)
            if batch_failed:
                print("Collection stopped after a worker failure; completed attempts were saved.", flush=True)
                break


def replay(evidence):
    outcomes = []

    def lookup(request):
        key = input_hash(context(request))
        history = evidence["attempts"].get(key, [])
        if not history:
            outcomes.append("uncollected")
            raise LookupError("No collected response")
        latest = history[-1]
        if "infrastructure_error" in latest:
            outcomes.append("infrastructure error")
            raise RuntimeError(latest["infrastructure_error"])
        outcomes.append("generated")
        return latest["artifact"]

    rows = author.grade(lookup)
    generated = outcomes.count("generated")
    passed = sum(result for _, result, _ in rows)
    print(f"Offline replay: {passed}/{generated} generated responses passed; "
          f"{outcomes.count('infrastructure error')} infrastructure errors; "
          f"{outcomes.count('uncollected')} uncollected.")
    for (name, passed_case, detail), outcome in zip(rows, outcomes, strict=True):
        status = ("pass" if passed_case else "fail") if outcome == "generated" else outcome
        print(f"  {name}: {status} — {detail}")
    if generated != len(rows):
        return 2
    return 0 if passed == generated else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="Call the existing Mac Codex author on uncached inputs")
    parser.add_argument("--fresh", action="store_true", help="Append a new live response even for cached successes")
    parser.add_argument("--limit", type=int, help="Maximum number of live calls for this invocation")
    args = parser.parse_args()
    if (args.fresh or args.limit is not None) and not args.collect:
        parser.error("--fresh and --limit require --collect")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    evidence = json.loads(EVIDENCE.read_text()) if EVIDENCE.exists() else {"version": 1, "attempts": {}}
    if args.collect:
        collect(evidence, inputs(), args.limit, args.fresh)
    return replay(evidence)


if __name__ == "__main__":
    raise SystemExit(main())
