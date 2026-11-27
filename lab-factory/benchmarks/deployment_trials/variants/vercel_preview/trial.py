"""Configure a fresh disposable Preview or run the common workload through its private API."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


HARNESS = Path(__file__).resolve().parents[2] / "acceptance.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "run", "observe", "offline", "verify"))
    parser.add_argument("--export", type=Path, required=True, help="The linked source archive used for Vercel deploy")
    parser.add_argument("--scratch", type=Path, required=True, help="Private local directory for fresh credentials")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--project", required=True, help="Dedicated new project named lf-trial-*")
    parser.add_argument("--origin", required=True, help="Unique lf-check-*.vercel.app test alias")
    args = parser.parse_args()
    linked = json.loads((args.export / ".vercel/project.json").read_text())
    url = urlsplit(args.origin)
    if (not args.project.startswith("lf-trial-") or linked["projectName"] != args.project
            or url.scheme != "https" or not (url.hostname or "").startswith("lf-check-")
            or not url.hostname.endswith(".vercel.app") or url.netloc != url.hostname or url.path
            or url.query or url.fragment):
        parser.error("Expected a linked disposable trial project and its dedicated HTTPS trial alias")
    args.scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.scratch.stat().st_mode & 0o077:
        parser.error("Use a scratch directory accessible only to the operator")
    credentials = args.scratch / "cloud-credentials.json"
    automation = args.scratch / "cloud-automation-key"
    common = [sys.executable, str(HARNESS)]
    options = ["--credentials", str(credentials), "--base-url", args.origin, "--allow-isolated-remote"]
    if args.action == "configure":
        subprocess.run([*common, "credentials", "--credentials", str(credentials)], check=True)
        values = json.loads(subprocess.check_output([*common, "env", *options]))
        for key, value in values.items():
            # Pass values via stdin. Never echo CLI output containing provider credentials.
            subprocess.run(["vercel", "env", "add", key, "preview", "--yes", "--sensitive",
                            "--scope", args.scope], input=value, text=True, cwd=args.export,
                           capture_output=True, check=True)
            print("Configured", key, flush=True)
        endpoint = "/v1/projects/" + linked["projectId"] + "/protection-bypass"
        cmd = ["vercel", "api", endpoint, "-X", "PATCH", "--input", "-", "--scope", args.scope]
        result = subprocess.run(cmd, input='{"generate":{}}', text=True, cwd=args.export,
                                capture_output=True, check=True)
        tokens = json.loads(result.stdout)["protectionBypass"]
        if len(tokens) != 1:
            raise RuntimeError("Expected one automation credential on the fresh disposable project")
        with os.fdopen(os.open(automation, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as out:
            out.write(next(iter(tokens)))
    else:
        env = dict(os.environ, LAB_TRIAL_PROTECTION_BYPASS=automation.read_text().strip())
        subprocess.run([*common, args.action, *options, "--state", str(args.scratch / "cloud-state.json")],
                       env=env, check=True)


if __name__ == "__main__":
    main()
