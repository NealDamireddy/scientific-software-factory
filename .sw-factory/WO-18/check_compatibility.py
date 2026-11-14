"""Exercise the actual pinned v1 client/server against the checked-out WO-18 versions.

Run from the repository root: python .sw-factory/WO-18/check_compatibility.py
"""
from contextlib import closing, contextmanager
from io import BytesIO
import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from factory.uvvis_adapter import VirtualInstrumentAdapter
from factory.uvvis_contract import InstrumentError, pin_sha256
from tests.test_uvvis_api import PIN, SAMPLES, SETTINGS

BASE = "ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08"


@contextmanager
def server(code, store, samples):
    args = [sys.executable, "-m", "factory.uvvis_http", "--store", str(store),
            "--samples", str(samples), "--duration", "60", "--port", "0"]
    with subprocess.Popen(args, cwd=code, stdout=subprocess.PIPE, text=True) as process:
        try:
            url = process.stdout.readline().strip()
            assert url.startswith("http://127.0.0.1:"), url
            yield url
        finally:
            process.terminate()
            process.wait(timeout=5)


def legacy(code, url, statement, job_id=""):
    setup = """import json, sys
from factory.uvvis_adapter import VirtualInstrumentAdapter
url, pin, settings, job_id = sys.argv[1:]
pin, settings = json.loads(pin), json.loads(settings)
client = VirtualInstrumentAdapter(url, pin["instrument_id"], pin["profile_id"], pin["profile_sha256"])
"""
    return json.loads(subprocess.check_output(
        [sys.executable, "-c", setup + statement, url, json.dumps(PIN), json.dumps(SETTINGS), job_id],
        cwd=code, text=True,
    ))


def main():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
        root = Path(tmp)
        old = root / "original"
        archive = subprocess.check_output(["git", "archive", BASE, "factory", "registry"], cwd=ROOT)
        with tarfile.open(fileobj=BytesIO(archive)) as files:
            files.extractall(old, filter="data")
        samples = root / "samples.json"
        samples.write_text(json.dumps(SAMPLES))
        start = """blank = client.blank(settings)
job = client.submit(settings, ["vial-q17"], blank["blank_id"], "compat")
print(json.dumps(job["job_id"]))"""
        with server(old, root / "old-store", samples) as origin:
            job = legacy(old, origin, start)
            updated = VirtualInstrumentAdapter(origin, PIN["instrument_id"], PIN["profile_id"], PIN["profile_sha256"])
            try:
                updated.cancel(job)
            except InstrumentError as error:
                assert error.status == 404, str(error)
            else:
                raise AssertionError("old server accepted updated client's cancellation")

            # Also hit the exact final POST, as if the server changed after a valid preflight.
            with closing(http.client.HTTPConnection(updated.host, updated.port, timeout=2)) as conn:
                conn.request("POST", f"/v1/acquisitions/{job}/cancel?pin_sha256={pin_sha256(PIN)}",
                             json.dumps(PIN), {"Content-Type": "application/json"})
                response = conn.getresponse()
                assert response.status == 404, response.status
                response.read()
            owner_state = legacy(old, origin, 'print(json.dumps(client.poll(job_id)["status"]))', job)
            assert owner_state == "running", owner_state
            print(f"old server: new client rejected, conditional POST 404, owner job {job} {owner_state}")
        with server(ROOT, root / "new-store", samples) as origin:
            job = legacy(old, origin, start)
            state, envelope = legacy(old, origin, """state = client.poll(job_id)["status"]
cancel = client.cancel(job_id)
assert cancel["status"] == "cancelled"
print(json.dumps([state, client.measurements(job_id)]))""", job)
            assert state == "running" and envelope == {
                "schema_version": 1, "job_id": job, "complete": False, "records": []}
            print(f"new server: old client submitted, polled, cancelled and retrieved partial job {job}")
            with closing(sqlite3.connect(root / "new-store/jobs.sqlite3")) as db:
                assert db.execute("SELECT status FROM jobs").fetchall() == [("cancelled",)]


if __name__ == "__main__":
    main()
