"""Install the signed-in Mac analysis author as a per-user launchd job."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

LABEL = "com.labfactory.analysis-author"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Production MCP URL")
    parser.add_argument("--worker", required=True, help="Name assigned to the MCP bearer token")
    parser.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args()
    uv, codex = shutil.which("uv"), shutil.which("codex")
    token = args.token_file.expanduser().resolve()
    if sys.platform != "darwin" or not uv or not codex or not token.is_file():
        parser.error("Use a signed-in Mac with uv, Codex and an existing agent token file.")
    project = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "pyproject.toml", "uv.lock"],
                               cwd=project, text=True):
        parser.error("Install the worker from a committed backend release.")
    root = Path.home() / ".local/share/labfactory/analysis-worker"
    venv = root / "releases" / revision / "venv"
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run([uv, "sync", "--locked", "--no-dev", "--no-editable", "--project", str(project)],
                   check=True, env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)})
    python = str(venv / "bin/python")
    subprocess.run([python, "-I", "-c", "import labfactory.tabular_worker"], check=True, cwd=root)
    plist = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    plist.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "Label": LABEL, "StartInterval": 90, "RunAtLoad": True, "ProcessType": "Background",
        "ProgramArguments": [python, "-I", "-m", "labfactory.tabular_worker", "--url", args.url,
                             "--worker", args.worker, "--token-file", str(token)],
        "WorkingDirectory": str(root), "StandardOutPath": str(logs / "author.log"),
        "StandardErrorPath": str(logs / "author-errors.log"),
        "EnvironmentVariables": {"HOME": str(Path.home()), "PATH": f"{Path(codex).parent}:/usr/bin:/bin:/usr/sbin:/sbin"},
    }
    domain = f"gui/{os.getuid()}"
    active = subprocess.run(["launchctl", "print", domain + "/" + LABEL], capture_output=True).returncode == 0
    if active and plist.exists() and plistlib.loads(plist.read_bytes()) == config:
        print(f"{LABEL} is already installed for {revision[:12]}.")
        return
    if active:
        subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], check=True)
    plist.write_bytes(plistlib.dumps(config))
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Installed {LABEL} for {revision[:12]}. Checks the shared queue every 90 seconds.")


if __name__ == "__main__":
    main()
