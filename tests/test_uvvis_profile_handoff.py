"""Check the context and instrument interfaces below specification approval."""
from contextlib import closing
from pathlib import Path
import tempfile
import threading
import unittest

from factory.context import ROOT, read_json
from factory.context_repository import SQLiteContextRepository
from factory.uvvis_adapter import VirtualInstrumentAdapter
from factory.uvvis_http import make_server
from factory.uvvis_service import VirtualUvVisService
from tests.test_context_repository import load_demo
from tests.test_uvvis_api import until


class InstrumentProfileHandoffTests(unittest.TestCase):
    def test_persisted_instance_matches_live_profile_and_readings(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        db = root / "context.sqlite"
        repo = SQLiteContextRepository(db)
        lab, project = load_demo(repo)
        # A protocol editor can serialize the JSON integer three as 3.0.
        settings = {**project.payload["measurement_settings"], "replicates": 3.0}
        project = repo.save_project({**project.payload, "measurement_settings": settings},
                                    expected_revision=project.revision)
        reopened = SQLiteContextRepository(db)
        pinned = reopened.get("project", project.lab_id, project_id=project.project_id,
                              revision=project.revision)
        inventory = reopened.get("lab", pinned.lab_id, revision=pinned.lab_revision)
        self.assertEqual((pinned.sha256, pinned.lab_sha256), (project.sha256, lab.sha256))
        self.assertEqual(inventory.sha256, pinned.lab_sha256)
        instance, = (item for item in inventory.payload["instruments"]
                     if item["instrument_id"] == pinned.payload["instrument_id"])
        settings = pinned.payload["measurement_settings"]
        self.assertIsInstance(settings["replicates"], float)
        unknown, = pinned.payload["sample_ids"]

        service = self.enterContext(closing(VirtualUvVisService(
            root / "jobs", {unknown: {"concentration_mg_l": 8}}, duration_s=0)))
        server = self.enterContext(make_server(service))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        adapter = VirtualInstrumentAdapter(f"http://127.0.0.1:{server.server_port}",
                                           instance["instrument_id"], instance["profile_id"],
                                           instance["profile_sha256"])
        capabilities = adapter.capabilities()
        self.assertEqual(capabilities["profile"], read_json(ROOT / "registry/virtual-uvvis.profile.json"))
        self.assertEqual(capabilities["profile_sha256"], instance["profile_sha256"])
        blank = adapter.blank(settings)
        job = adapter.submit(settings, [unknown], blank["blank_id"], "profile-handoff")
        until(lambda: adapter.poll(job["job_id"])["status"] == "completed")
        result = adapter.measurements(job["job_id"])
        self.assertTrue(result["complete"])
        self.assertEqual([row["replicate"] for row in result["records"]], [1, 2, 3])
        for row in result["records"]:
            self.assertEqual((row["wavelength_nm"], row["path_length_mm"]), (650, 10))
            self.assertEqual((row["job_id"], row["blank_id"], row["sample_id"]),
                             (job["job_id"], blank["blank_id"], unknown))
            for field in ("instrument_id", "profile_id", "profile_sha256"):
                self.assertEqual(row[field], instance[field])
            self.assertIs(row["simulated"], True)
