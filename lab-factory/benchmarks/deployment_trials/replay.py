"""Run the four isolated loopback deployments and compare their receipts."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from compare import compare, read_receipt


HERE = Path(__file__).resolve().parent
STACKS = ("single_host", "libsql", "replicas", "vercel_blob")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New directory for this run")
    parser.add_argument("--sqld", type=Path, help="Pinned local libSQL server executable")
    parser.add_argument("--replica-port", type=int, default=18460, help="First of three adjacent loopback ports")
    parser.add_argument("--variants", nargs="+", choices=STACKS, default=list(STACKS))
    args = parser.parse_args()
    if len(set(args.variants)) != len(args.variants):
        parser.error("Each variant can run once per output directory")
    if "libsql" in args.variants and (args.sqld is None or not args.sqld.is_file()):
        parser.error("Supply the pinned --sqld executable or select --variants without libsql")
    if args.output.exists():
        parser.error("Use a new output directory")
    root = args.output.resolve()
    root.mkdir(parents=True, mode=0o700)
    receipts = {}
    for name in args.variants:
        folder = root / name
        folder.mkdir(mode=0o700)
        cmd = [sys.executable, str(HERE / "variants" / name / "trial.py")]
        evidence = folder / "evidence.json"
        if name == "replicas":
            cmd.extend(["--port", str(args.replica_port), "--output", str(folder)])
        else:
            cmd.extend(["--output", str(evidence)])
        if name == "libsql":
            cmd.extend(["--sqld", str(args.sqld.resolve())])
        print(f"Starting {name}", flush=True)
        subprocess.run(cmd, check=True)
        receipts[name] = read_receipt(folder / "acceptance.json" if name == "replicas" else evidence)

    if len(receipts) > 1:
        result = compare(receipts)
        (root / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"Deployment parity: {result['parity']}. Evidence saved in {root}.")
        return 0 if result["parity"] else 1
    return 0 if all(r["verified"] for r in receipts.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
