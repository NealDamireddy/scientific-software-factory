"""Serve the exported demo, its optical simulator and the local Codex worker."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from subprocess import SubprocessError
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from api.instrument import CALIBRATION, handler as InstrumentHandler, read_vial
from factory import b12_build
from factory.optics import RECIPE, verify_candidate
from factory.sandbox import execute

ROOT = Path(__file__).resolve().parents[1]
PAPER = json.loads((ROOT / "data/b12-evaluation.json").read_text())["published"]
PAPER_SAMPLE = next(row for row in PAPER["samples"] if row["prepared_ppm"] == 10)
BUILD_LOCK = Lock()


def generate(spec, store):
    if not isinstance(spec, dict):
        raise ValueError("Insert the experiment specs before generating.")
    supported = {
        "sample": "Vial A", "analyte": "vitamin B12", "wavelength_nm": RECIPE["wavelength_nm"],
        "readings": RECIPE["replicates"], "light_path_mm": CALIBRATION["standards"][0]["raw"][0]["settings"]["path_length_mm"],
        "standards_mg_l": [s["concentration_mg_l"] for s in CALIBRATION["standards"]],
        "output": "concentration in mg/L; withhold outside calibration",
    }
    title = spec.get("application_name")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError("Enter an application name of 1 to 100 characters.")
    if {key: value for key, value in spec.items() if key != "application_name"} != supported:
        raise ValueError("This simulator supports the displayed B12 protocol. Insert its specs and optionally edit the application name.")
    folder = store / uuid4().hex
    folder.mkdir()
    brief = "Use the supplied application_name as views.title. Experiment specifications: " + json.dumps(spec)
    receipt = b12_build.build(brief, folder)
    checks = verify_candidate(folder / "analysis.py")
    if not all(check["pass"] for check in checks):
        raise ValueError("Generated analysis failed verification. Generate again.")
    revision = b12_build.revision(folder)
    files = {name: (folder / name).read_text() for name in b12_build.FILES}
    if json.loads(files["views.json"])["title"] != title:
        raise ValueError("Generated title did not match the requested application name. Generate again.")
    (folder / "verified").write_text(revision)
    return {"id": folder.name, "revision": revision, "files": files, "spec": spec,
            "worker": receipt, "checks": [c["name"] for c in checks]}


def run_generated(task_id, store):
    if not isinstance(task_id, str) or len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
        raise ValueError("Generate an application first.")
    folder = store / task_id
    if not (folder / "verified").exists():
        raise ValueError("Generate the application again in this presenter session.")
    revision = b12_build.revision(folder)
    if revision != (folder / "verified").read_text():
        raise ValueError("The generated files have changed. Generate again.")
    files = {name: (folder / name).read_text() for name in b12_build.FILES}
    receipt = read_vial(revision, files, "A", "vial-A", str(uuid4()))
    payload = receipt["analysis_input"]
    # The published mean is one observation. Repeat it only to meet the recipe's input shape.
    paper_input = {**payload, "sample_id": PAPER_SAMPLE["id"],
                   "absorbances": [PAPER_SAMPLE["mean_absorbance"]] * RECIPE["replicates"]}
    source = folder / "analysis.py"
    output, sandbox = execute(source, json.dumps(payload).encode())
    paper_output, _ = execute(source, json.dumps(paper_input).encode())
    return {"acquisition": receipt, "analysis": {"output": output, "paperOutput": paper_output,
            "paperInput": paper_input, "runtime": sandbox}}


class DemoHandler(InstrumentHandler, SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/presenter":
            return self.reply(200, {"generation": True})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/instrument":
            return super().do_POST()
        if self.path not in ("/api/presenter/generate", "/api/presenter/run"):
            return self.send_error(404)
        host = "127.0.0.1:8776"
        if (self.headers.get("Host") != host or self.headers.get("Origin") != "http://" + host
                or self.headers.get_content_type() != "application/json"):
            return self.reply(403, {"error": "Open the presenter at http://127.0.0.1:8776/b12/demo/."})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 8192:
                return self.reply(400, {"error": "Enter a specification under 8 KB."})
            body = json.loads(self.rfile.read(size))
            if self.path.endswith("/run"):
                result = run_generated(body, self.server.builds)
            else:
                if not BUILD_LOCK.acquire(blocking=False):
                    return self.reply(409, {"error": "Another generation is already running."})
                try:
                    result = generate(body, self.server.builds)
                finally:
                    BUILD_LOCK.release()
        except (OSError, ValueError, RuntimeError, SubprocessError) as exc:
            return self.reply(400, {"error": str(exc)[:500]})
        self.reply(200, result)


if __name__ == "__main__":
    export = ROOT / "out"
    if not (export / "b12/demo/index.html").exists():
        raise SystemExit("Run npm run build first.")
    with TemporaryDirectory() as store, ThreadingHTTPServer(("127.0.0.1", 8776), partial(DemoHandler, directory=export)) as server:
        server.builds = Path(store)
        print("Lab projects: http://127.0.0.1:8776/", flush=True)
        server.serve_forever()
