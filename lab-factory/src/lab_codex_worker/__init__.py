"""Local Codex CLI launcher shared by Lab Factory and the EVOLVE workbench."""

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile


@dataclass(frozen=True)
class WorkerResponse:
    answer: dict
    stderr: str
    cli_version: str | None


def run_worker(
    prompt: str,
    schema_json: str,
    *,
    timeout: int,
    failure_message: Callable[[subprocess.CompletedProcess], str],
    include_version: bool = False,
    temp_prefix: str | None = None,
) -> WorkerResponse:
    """Run one tool-free request in a fresh directory and read its JSON answer."""
    with tempfile.TemporaryDirectory(prefix=temp_prefix) as scratch:
        work = Path(scratch)
        (work / "schema.json").write_text(schema_json)
        answer = work / "answer.json"
        # Keep the local CLI sign-in available without forwarding reviewer or MCP credentials.
        env = {key: os.environ[key] for key in ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG") if key in os.environ}
        version = None
        if include_version:
            version = subprocess.check_output(["codex", "--version"], text=True, env=env, timeout=10).strip()
        command = [
            "codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "-c", 'approval_policy="never"',
            "-c", 'web_search="disabled"', "--disable", "shell_tool", "--disable", "unified_exec",
            "--disable", "apps", "--disable", "plugins", "--disable", "skill_search",
            "--output-schema", "schema.json", "--output-last-message", "answer.json", "-",
        ]
        result = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=work, env=env, timeout=timeout)
        if result.returncode or not answer.exists():
            raise RuntimeError(failure_message(result))
        return WorkerResponse(json.loads(answer.read_text()), result.stderr, version)
