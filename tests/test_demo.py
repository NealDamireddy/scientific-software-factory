import io
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from factory import demo


class DemoTests(unittest.TestCase):
    def test_archive_only_is_available_without_sandbox_or_worker(self):
        with patch.object(demo, "check_sandbox", side_effect=RuntimeError("nested sandbox unavailable")), \
                patch.object(demo, "check_worker") as worker:
            checks, bundle = demo.readiness(0, demo.ROOT / "public/b12/completed.json", archive_only=True)
        self.assertIsNotNone(bundle)
        self.assertFalse(any(status == "FAIL" for status, _, _ in checks))
        self.assertIn(("WARN", "Offline sandbox", "nested sandbox unavailable"), checks)
        worker.assert_not_called()

    def test_fresh_mode_requires_sandbox_and_worker(self):
        with patch.object(demo, "check_sandbox", side_effect=RuntimeError("sandbox missing")), \
                patch.object(demo, "check_worker", side_effect=RuntimeError("worker missing")):
            checks, _ = demo.readiness(0, demo.ROOT / "public/b12/completed.json")
        self.assertEqual({name for status, name, _ in checks if status == "FAIL"},
                         {"Offline sandbox", "Archive replay", "Coding worker"})

    def test_full_readiness_reexecutes_saved_analyses(self):
        with patch.object(demo, "check_sandbox", return_value="working isolation"), \
                patch.object(demo, "check_worker", return_value="worker ready"), \
                patch("factory.replay_bundle.replay_package") as replay:
            checks, bundle = demo.readiness(0, demo.ROOT / "public/b12/completed.json")
        self.assertFalse(any(status == "FAIL" for status, _, _ in checks))
        replay.assert_called_once_with(bundle)

    def test_tampered_archive_blocks_even_view_only_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"profile":"unsupported"}')
            with patch.object(demo, "check_sandbox", side_effect=RuntimeError("no sandbox")):
                checks, bundle = demo.readiness(0, path, archive_only=True)
            self.assertIsNone(bundle)
            self.assertIn("Previous run", [name for status, name, _ in checks if status == "FAIL"])

    def test_port_available_immediately_after_presenter_connection_closes(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            address = listener.getsockname()
            with socket.create_connection(address, timeout=2) as client:
                connection, _ = listener.accept()
                connection.close()
                self.assertEqual(client.recv(1), b"")
        self.assertEqual(demo.check_port(address[1]), "Loopback port is available")

    def test_port_conflict_is_reported(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "Stop the previous presenter"):
                demo.check_port(listener.getsockname()[1])

    def test_check_never_serves_or_invokes_model(self):
        with patch.object(demo, "readiness", return_value=([("PASS", "Test", "ready")], {})), \
                patch("factory.lab.serve") as serve, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(demo.main(["--check"]), 0)
        serve.assert_not_called()

    def test_failed_readiness_never_starts_server(self):
        with patch.object(demo, "readiness", return_value=([("FAIL", "Test", "missing")], None)), \
                patch("factory.lab.serve") as serve, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(demo.main([]), 1)
        serve.assert_not_called()

    def test_archive_only_startup_disables_generation(self):
        with patch.object(demo, "readiness", return_value=([("WARN", "Sandbox", "missing")], {"saved": True})), \
                patch("factory.lab.serve") as serve, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(demo.main(["--archive-only", "--port", "8766"]), 0)
        self.assertFalse(serve.call_args.kwargs["allow_generation"])
        self.assertEqual(serve.call_args.kwargs["archive"], {"saved": True})

    def test_worker_check_reports_missing_login_without_auth_output(self):
        with patch.object(demo.shutil, "which", return_value="/bin/codex"), \
                patch.object(demo.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0),
                     subprocess.CalledProcessError(1, ["codex"], stderr="sensitive authentication output")]):
            with self.assertRaisesRegex(RuntimeError, "codex login") as error:
                demo.check_worker()
            self.assertNotIn("sensitive", str(error.exception))

    def test_sandbox_probe_rejects_permissive_execution(self):
        with patch("factory.sandbox.execute", return_value=({"mean": 2, "denied_read": False,
                "denied_write": True, "denied_network": True}, "fake sandbox")):
            with self.assertRaisesRegex(RuntimeError, "did not deny"):
                demo.check_sandbox()

    def test_sandbox_probe_checks_exact_positive_and_negative_results(self):
        with patch("factory.sandbox.execute", return_value=({"mean": 2, "denied_read": True,
                "denied_write": True, "denied_network": True}, "test fixture")):
            self.assertIn("probes denied", demo.check_sandbox())
