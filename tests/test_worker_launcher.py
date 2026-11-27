"""Exercise the EVOLVE worker contract without invoking the Codex CLI."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from factory.agent import invoke_worker


class WorkerLauncherTests(unittest.TestCase):
    def test_request_and_provenance_with_or_without_model_identifier(self):
        env = {"PATH": "/usr/bin", "HOME": "/test-home", "LANG": "C", "CODEX_HOME": "/test-codex"}
        schema = {"type": "object", "required": ["source"]}
        answer = {"source": "answer"}
        for stderr, model in [("model: chosen-model\n", "chosen-model"), ("", "CLI default (identifier unavailable)")]:
            with self.subTest(stderr=stderr):
                workdirs = []

                def run(command, *, cwd, env, input, timeout, capture_output, text):
                    work = Path(cwd)
                    workdirs.append(work)
                    self.assertEqual(command[:2], ["codex", "exec"])
                    self.assertEqual(command[-1], "-")
                    self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
                    self.assertTrue({"--ignore-user-config", "--ignore-rules", "--ephemeral",
                                     "--skip-git-repo-check", 'approval_policy="never"', 'web_search="disabled"'} <= set(command))
                    disabled = {command[i + 1] for i, flag in enumerate(command) if flag == "--disable"}
                    self.assertTrue({"shell_tool", "unified_exec", "apps", "plugins", "skill_search"} <= disabled)
                    self.assertEqual((input, timeout, capture_output, text), ("measurement request", 180, True, True))
                    schema_path = work / command[command.index("--output-schema") + 1]
                    self.assertEqual(json.loads(schema_path.read_text()), schema)
                    (work / command[command.index("--output-last-message") + 1]).write_text(json.dumps(answer))
                    return subprocess.CompletedProcess(command, 0, "", stderr)

                with patch.dict(os.environ, {**env, "EXTRA_TOKEN": "private"}, clear=True), \
                     patch("subprocess.check_output", return_value="codex-cli test\n") as version, \
                     patch("subprocess.run", side_effect=run) as execution:
                    message, receipt = invoke_worker("measurement request", schema)
                version.assert_called_once_with(["codex", "--version"], text=True, env=env, timeout=10)
                self.assertEqual(execution.call_args.kwargs["env"], env)
                self.assertEqual(message, answer)
                self.assertEqual(receipt, {"method": "codex exec", "cli": "codex-cli test", "model": model,
                                           "attempts": 1, "timeout_s": 180, "tool_mode": "read-only, tool-free request"})
                self.assertEqual(len(workdirs), 1)
                self.assertFalse(workdirs[0].exists())

    def test_failed_request_removes_scratch_and_preserves_errors(self):
        cases = [
            (1, "{}", "early error\nignored\nERROR: last failure", RuntimeError, "ERROR: last failure"),
            (0, None, "", RuntimeError, "exit 0"),
            (0, "invalid", "", json.JSONDecodeError, None),
        ]
        for returncode, output, stderr, error, detail in cases:
            with self.subTest(returncode=returncode, output=output):
                workdirs = []

                def run(command, *, cwd, **kwargs):
                    work = Path(cwd)
                    workdirs.append(work)
                    if output is not None:
                        (work / command[command.index("--output-last-message") + 1]).write_text(output)
                    return subprocess.CompletedProcess(command, returncode, "", stderr)

                with patch("subprocess.check_output", return_value="test"), patch("subprocess.run", side_effect=run), \
                     self.assertRaises(error) as raised:
                    invoke_worker("request", {"type": "object"})
                if detail:
                    self.assertEqual(str(raised.exception), "Codex failed: " + detail)
                self.assertEqual(len(workdirs), 1)
                self.assertFalse(workdirs[0].exists())
