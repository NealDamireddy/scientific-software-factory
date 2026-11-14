from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from factory.archive import validate_archive
from factory.context import ROOT, read_json
from factory.lab import Handler, Lab, ThreadingHTTPServer


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.bundle = read_json(ROOT / "public/b12/completed.json")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.lab = Lab(Path(self.temp.name), archive=self.bundle, allow_generation=False)
        self.addCleanup(self.lab.close)
        self.direct = self.bundle["direct"]["id"]
        self.child = self.bundle["followup"]["id"]

    def test_empty_store_has_original_read_only_run(self):
        tasks = self.lab.history()
        self.assertEqual({task["id"] for task in tasks}, {self.direct, self.child})
        for task in tasks:
            self.assertTrue(task["archived"])
            self.assertEqual(task["mode"], "previous completed run")
        self.assertEqual(self.lab.source(self.child), self.bundle["sources"][self.child])
        self.assertEqual(self.lab.evidence(self.child), self.bundle)
        self.assertFalse(list(Path(self.temp.name).glob("*/task.json")))

    def test_archive_is_not_changed_by_clients_or_mutations(self):
        self.lab.task(self.child)["result"]["concentration_mg_l"] = -1
        self.lab.source(self.child)["files"]["analysis.py"] = "changed"
        self.lab.evidence(self.child)["initial"]["calibration"]["slope"] = 9
        for action in (self.lab.approve, self.lab.rerun, self.lab.reveal, self.lab.retry):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "read-only"):
                action(self.child)
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.lab.prepare(self.child, {})
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.lab.update(self.child, status="failed")
        self.assertEqual(self.lab.evidence(self.child), self.bundle)

    def test_archive_only_never_invokes_worker(self):
        with patch.object(self.lab.pool, "submit") as worker:
            with self.assertRaisesRegex(ValueError, "Archive-only"):
                self.lab.submit("Measure B12 at 550 nm")
            worker.assert_not_called()

    def test_archive_only_ignores_live_store_even_when_running_or_ids_overlap(self):
        store = Path(self.temp.name) / "presenter"
        live = Lab(store)
        self.addCleanup(live.close)
        active_id = "a" * 32
        for identifier in (active_id, self.child):
            folder = store / identifier
            folder.mkdir()
            (folder / "task.json").write_text('{"status":"generating"}')
        previous = Lab(store, archive=self.bundle, allow_generation=False)
        self.addCleanup(previous.close)
        self.assertEqual({t["id"] for t in previous.history()}, {self.direct, self.child})
        self.assertTrue(previous.task(self.child)["archived"])
        self.assertEqual(previous.evidence(self.child), self.bundle)
        with self.assertRaises(FileNotFoundError):
            previous.task(active_id)
        for identifier in (active_id, self.child):
            self.assertEqual(read_json(store / identifier / "task.json"), {"status": "generating"})

    def test_replay_reexecutes_without_changing_retained_evidence(self):
        with patch("factory.replay_bundle.replay_package") as replay:
            self.assertTrue(self.lab.replay(self.child)["replay"]["parent_matches"])
            replay.assert_called_once_with(self.bundle)
        with patch("factory.replay_bundle.replay_package", side_effect=RuntimeError("sandbox blocked")):
            with self.assertRaisesRegex(RuntimeError, "sandbox blocked"):
                self.lab.replay(self.child)
        self.assertEqual(self.lab.evidence(self.child), self.bundle)

    def test_bad_archive_is_rejected_before_creating_store(self):
        for change in ("source", "calibration", "lineage", "recipe", "preparation", "task-id"):
            altered = deepcopy(self.bundle)
            if change == "source":
                altered["sources"][self.child]["files"]["analysis.py"] += "# changed"
            elif change == "calibration":
                altered["initial"]["calibration"]["slope"] = 4
            elif change == "lineage":
                altered["followup"]["parent_revision"] = "changed"
            elif change == "recipe":
                altered["sources"][self.child]["files"]["recipe.json"] = '{}'
            elif change == "preparation":
                altered["followup"]["preparation"]["sample_ml"] = 3
            else:
                altered["direct"]["id"] = "../outside"
            store = Path(self.temp.name) / "new-store"
            with self.subTest(change=change), self.assertRaises(ValueError):
                Lab(store, archive=altered)
            self.assertFalse(store.exists())

    def test_live_store_is_preserved_and_archived_run_is_still_available(self):
        with patch("factory.b12_build.invoke_worker", side_effect=RuntimeError("test worker unavailable")):
            live = Lab(Path(self.temp.name) / "live", archive=self.bundle)
            self.addCleanup(live.close)
            submitted = live.submit("Measure B12 at 550 nm")
            live.pool.shutdown()
        self.assertEqual(live.task(submitted["id"])["status"], "failed")
        self.assertEqual(live.source(self.child), self.bundle["sources"][self.child])
        self.assertEqual(len(live.history()), 3)

    def test_missing_package_fields_fail_as_validation_errors(self):
        for bundle in ({}, {"profile": "wrong"}, {**self.bundle, "sources": None}):
            with self.assertRaises(ValueError):
                validate_archive(bundle)

    def test_http_archive_routes_and_private_path_denial(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_port
        server.lab = self.lab
        server.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{port}"
        with urlopen(base + "/api/tasks") as response:
            self.assertFalse(json.load(response)["allow_generation"])
        for suffix in ("", "/source", "/evidence"):
            with urlopen(base + "/api/tasks/" + self.child + suffix) as response:
                self.assertEqual(response.status, 200)
                self.assertIsInstance(json.load(response), dict)
        for path in ("/api/tasks/" + self.direct + "/private.json", "/public/b12/completed.json", "/../private.json"):
            with self.assertRaises(HTTPError) as error:
                urlopen(base + path)
            self.assertEqual(error.exception.code, 404)
        foreign = Request(base + "/api/tasks", headers={"Origin": "https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(foreign)
        self.assertEqual(error.exception.code, 403)
        submit = Request(base + "/api/tasks", data=b'{"brief":"B12 at 550 nm"}',
                         headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(submit)
        self.assertEqual(error.exception.code, 400)
