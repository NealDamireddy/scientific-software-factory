"""Presenter-laptop EVOLVE service. Start with python -m factory.lab."""
import argparse
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import difflib
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import platform
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
import uuid

from . import b12_build
from .archive import validate_archive
from .context import ROOT, read_json
from .optics import PROFILE, RECIPE, validate_preparation, acquire, assess, calibration_digest, fit_calibration, validate_recipe, verify_candidate
from .sandbox import execute
from .followup import run_followup, replay_acquisition


def save(path, obj):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False))
    temporary.replace(path)


class Lab:
    def __init__(self, store, *, archive=None, allow_generation=True):
        self.archive = validate_archive(archive) if archive is not None else None
        self.archived = ({task["id"]: task for task in (self.archive["direct"], self.archive["followup"])}
                         if self.archive else {})
        self.allow_generation = allow_generation
        self.store = Path(store)
        self.store.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lease = (self.store / ".lock").open("a")
        fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        for task in self.history():
            if task["status"] in ("queued", "generating", "verifying"):
                self.update(task["id"], status="failed", error="Presenter stopped before this build completed")

    def close(self):
        self.pool.shutdown()
        self.lease.close()

    def history(self):
        live = {p.parent.name: self.task(p.parent.name) for p in self.store.glob("*/task.json")}
        saved = [self.task(identifier) for identifier in self.archived if identifier not in live]
        return sorted([*live.values(), *saved], key=lambda r: r["created"], reverse=True)

    def path(self, task_id):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("Invalid task ID")
        folder = self.store / task_id
        if not folder.is_dir():
            raise FileNotFoundError("Task does not exist")
        return folder

    def task(self, task_id):
        if task_id in self.archived and not (self.store / task_id).exists():
            return {**deepcopy(self.archived[task_id]), "mode": "previous completed run", "archived": True}
        task = read_json(self.path(task_id) / "task.json")
        if task["status"] == "verified" and not task.get("parent_id") and task.get("finding", {}).get("above_range"):
            data = read_json(self.path(task_id)/"acquisition.json")
            task["proposal"] = {
                "reason": (f"All three readings ({', '.join(format(n, '.5f') for n in task['finding']['absorbances'])}) "
                           f"exceed the strongest standard ({data['calibration']['high']:.5f}). "
                           "The protocol permits a twofold dilution followed by three fresh readings."),
                "protocol": PROFILE["protocol"], "upper_standard": data["calibration"]["high"],
                "readings": task["finding"]["absorbances"], "volumes": "One volume sample plus one volume matching solvent",
                "requirement": "Trace a prepared vial to its parent and use the actual volumes to recover its original concentration.",
            }
        return task

    def require_live(self, task_id):
        if self.task(task_id).get("archived"):
            raise ValueError("Previous completed runs are read-only; submit a new PI request for fresh generation")

    def update(self, task_id, **fields):
        self.require_live(task_id)
        with self.lock:
            task = {**read_json(self.path(task_id) / "task.json"), **fields}
            save(self.path(task_id) / "task.json", task)
            return task

    def submit(self, brief):
        if not isinstance(brief, str) or not 1 <= len(brief.strip()) <= 4000:
            raise ValueError("Enter a B12 request of up to 4000 characters")
        for wavelength in re.findall(r"(\d+(?:\.\d+)?)\s*(?:nm|nanomet(?:er|re)s?)\b", brief, re.I):
            if float(wavelength) != RECIPE["wavelength_nm"]:
                raise ValueError("The simulated instrument implements only the 550 nm channel")
        return self.enqueue(brief)

    def enqueue(self, brief, **fields):
        if not self.allow_generation:
            raise ValueError("Archive-only mode: fresh generation is disabled. Run python -m factory.demo --check on the presenter laptop")
        with self.lock:
            task_id = uuid.uuid4().hex
            folder = self.store / task_id
            folder.mkdir(mode=0o700)
            task = dict(id=task_id, brief=brief.strip(), status="queued", context=PROFILE,
                        created=datetime.now(timezone.utc).isoformat(), mode="fresh generation", **fields)
            save(folder / "task.json", task)
            self.pool.submit(self.generate, task_id)
            return task

    def approve(self, task_id):
        self.require_live(task_id)
        with self.lock:
            original = self.task(task_id)
            if not original.get("proposal") or original.get("parent_id"):
                raise ValueError("A verified direct above-range run is required")
            for task in self.history():
                if task.get("parent_id") == task_id:
                    return self.task(task["id"])
            if b12_build.revision(self.path(task_id)) != original["revision"]:
                raise ValueError("Parent source digest mismatch")
            return self.enqueue(original["proposal"]["requirement"], parent_id=task_id,
                                parent_revision=original["revision"], approval={
                                    "approved_at": datetime.now(timezone.utc).isoformat(),
                                    "origin": task_id, "factor": 2, "protocol": PROFILE["protocol"]})

    def prepare(self, task_id, data):
        self.require_live(task_id)
        with self.lock:
            task = self.task(task_id)
            if not task.get("approval"):
                raise ValueError("Approve follow-up before recording preparation")
            child = data.get("sample_id")
            if not isinstance(child, str) or not child.strip() or len(child) > 120:
                raise ValueError("Enter a prepared vial ID")
            prep = {key: data.get(key) for key in ("parent_id", "sample_ml", "final_ml", "unit")}
            prep["id"] = "prep-" + task_id
            factor = validate_preparation(child, prep)
            if prep["parent_id"] != "U-01" or not math.isclose(factor,task["approval"]["factor"]):
                raise ValueError("Preparation differs from approved parent or factor")
            prep["sample_id"] = child
            if task.get("preparation") and prep != task["preparation"]:
                raise ValueError("Preparation already recorded")
            return self.update(task_id, preparation=prep)

    def retry(self, task_id):
        self.require_live(task_id)
        with self.lock:
            task = self.task(task_id)
            if task["status"] != "failed" or not task.get("approval"):
                raise ValueError("Only a failed approved revision can retry")
            task = self.update(task_id, status="queued", error=None, checks=[], worker=None,
                               revision=None, attempts=task.get("attempts",1)+1)
            self.pool.submit(self.generate, task_id)
            return task

    def revise(self, task, folder):
        parent = self.path(task["parent_id"])
        if b12_build.revision(parent) != task["parent_revision"]:
            raise ValueError("Parent source digest mismatch")
        previous = verify_candidate(parent/"analysis.py", prepared=True)
        self.update(task["id"], parent_checks=previous)
        if all(case["pass"] for case in previous):
            raise ValueError("The parent already supports the requested capability")
        receipt = b12_build.build(task["brief"], folder, (parent/"analysis.py").read_text())
        revision = b12_build.revision(folder)
        if revision == task["parent_revision"]:
            raise ValueError("The candidate has no source changes")
        self.update(task["id"], status="verifying", worker=receipt, revision=revision)
        checks = verify_candidate(folder/"analysis.py", prepared=True)
        self.update(task["id"], checks=checks)
        if not checks or not all(case["pass"] for case in checks):
            raise ValueError("Prepared-sample release failed its independent requirements")
        self.update(task["id"], status="verified", views=read_json(folder/"views.json"))

    def collect(self, task_id):
        folder = self.path(task_id)
        recipe = validate_recipe(RECIPE)
        calibration = fit_calibration(recipe, secrets.randbits(63))
        # Separate blind label record. Neither the worker nor the analyst is given this file.
        label = 30 + secrets.randbelow(9)
        save(folder / "private.json", {"prepared_mg_l": label})
        raw = acquire(recipe, label, secrets.randbits(63), sample_id="U-01")
        finding = assess(raw, calibration)
        payload = dict(sample_id="U-01", absorbances=finding["absorbances"],
                       calibration={k: calibration[k] for k in ("id","slope","intercept","low","high")},
                       preparation=None)
        acquisition = dict(raw=raw, calibration=calibration, input=payload, finding=finding)
        save(folder / "acquisition.json", acquisition)
        self.update(task_id, acquisition_status="collected")
        return acquisition

    def generate(self, task_id):
        try:
            task = self.update(task_id, status="generating")
            folder = self.path(task_id)
            if task.get("parent_id"):
                self.revise(task, folder)
                return
            with ThreadPoolExecutor(max_workers=1) as bench:
                acquisition = bench.submit(self.collect, task_id)
                receipt = b12_build.build(task["brief"], folder)
            self.update(task_id, status="verifying", worker=receipt, revision=b12_build.revision(folder))
            checks = verify_candidate(folder / "analysis.py")
            if not checks or not all(check["pass"] for check in checks):
                self.update(task_id, checks=checks)
                raise ValueError("Independent assay requirements failed")
            measurement = acquisition.result()
            payload = measurement["input"]
            calibration = measurement["calibration"]
            finding = measurement["finding"]
            result, runtime = execute(folder / "analysis.py", json.dumps(payload).encode())
            if (result.get("sample_id") != "U-01" or result.get("calibration_id") != calibration["id"]
                    or result.get("status") != ("ok" if finding["in_range"] else "review")):
                raise ValueError("Actual sample result disagrees with trusted range or provenance check")
            if not finding["in_range"] and result.get("concentration_mg_l") is not None:
                raise ValueError("Candidate returned an out-of-range concentration")
            if finding["in_range"]:
                reference = (sum(finding["absorbances"])/3 - calibration["intercept"]) / calibration["slope"]
                actual = result.get("concentration_mg_l")
                if type(actual) not in (float, int) or not math.isclose(actual, reference, abs_tol=1e-7):
                    raise ValueError("Actual sample concentration disagrees with the frozen calibration")
            self.update(task_id, status="verified", checks=checks, result=result, finding=finding,
                        sandbox=runtime, views=read_json(folder / "views.json"))
        except Exception as error:
            self.update(task_id, status="failed", error=str(error)[:1800])

    def rerun(self, task_id):
        self.require_live(task_id)
        with self.lock:
            child = self.task(task_id)
            if child.get("status") != "verified" or not child.get("preparation") or not child.get("approval"):
                raise ValueError("Both a recorded preparation and a verified revision are required")
            if child.get("measurement"):
                return child
            parent = self.task(child["parent_id"])
            measurement = run_followup(self.path(parent["id"]), self.path(task_id), parent, child)
            return self.update(task_id, measurement=measurement, result=measurement["result"])

    def reveal(self, task_id):
        self.require_live(task_id)
        with self.lock:
            child = self.task(task_id)
            if not child.get("measurement") or child["result"]["status"] != "ok":
                raise ValueError("Save an in-range follow-up estimate before revealing its label")
            if child.get("score"):
                return child
            prepared = read_json(self.path(child["parent_id"])/"private.json")["prepared_mg_l"]
            prediction = child["result"]["concentration_mg_l"]
            return self.update(task_id, score=dict(prepared_mg_l=prepared, predicted_mg_l=prediction,
                                                   signed_error_mg_l=prediction-prepared))

    def replay(self, task_id):
        if self.task(task_id).get("archived"):
            if task_id != self.archive["followup"]["id"]:
                raise ValueError("Select the archived follow-up to replay both acquisitions")
            from .replay_bundle import replay_package
            replay_package(self.archive)
            return {**self.task(task_id), "replay": dict(parent_matches=True, child_matches=True,
                    calibration_id=self.archive["initial"]["calibration"]["id"])}
        with self.lock:
            child = self.task(task_id)
            if not child.get("measurement"):
                raise ValueError("A completed follow-up is required for replay")
            parent = self.task(child["parent_id"])
            first = read_json(self.path(parent["id"])/"acquisition.json")
            cal = first["calibration"]
            matches = []
            for task, measurement in [(parent, first), (child, child["measurement"])]:
                folder = self.path(task["id"])
                if b12_build.revision(folder) != task["revision"]:
                    raise ValueError("Stored app revision mismatch")
                output = replay_acquisition(folder, measurement, cal)
                matches.append(output == task["result"])
            if not all(matches):
                raise ValueError("Replay differed from recorded output")
            return self.update(task_id, replay=dict(parent_matches=True, child_matches=True, calibration_id=cal["id"]))

    def evidence(self, task_id):
        if self.task(task_id).get("archived"):
            if task_id != self.archive["followup"]["id"]:
                raise ValueError("Select the archived follow-up to download its evidence")
            return deepcopy(self.archive)
        with self.lock:
            child = self.task(task_id)
            if not child.get("measurement"):
                raise ValueError("Save the follow-up measurement before exporting evidence")
            parent = self.task(child["parent_id"])
            acquisition = read_json(self.path(parent["id"])/"acquisition.json")
            files = {}
            for task in (parent, child):
                folder = self.path(task["id"])
                if b12_build.revision(folder) != task["revision"]:
                    raise ValueError("Stored app revision mismatch")
                files[task["id"]] = self.source(task["id"])
            cal = acquisition["calibration"]
            if calibration_digest(cal) != cal["id"] or cal["id"] != child["measurement"]["calibration_id"]:
                raise ValueError("Follow-up calibration mismatch")
            if parent["result"].get("calibration_id") != cal["id"] or child["result"].get("calibration_id") != cal["id"]:
                raise ValueError("Recorded results disagree with calibration")
            checks = [
                ("Raw measurements retained", "initial.raw, initial.calibration.standards, followup.measurement.raw"),
                ("Acquisition settings recorded", "initial.raw[].settings, followup.measurement.raw[].settings"),
                ("Calibration unchanged", cal["id"]),
                ("Preparation documented", child["preparation"]["id"]),
                ("Software and dependencies identified", "sources, environment, direct.worker, followup.worker"),
                ("Numerical tests passed", "direct.checks, followup.parent_checks, followup.checks"),
                ("Outstanding scientific review shown", "scientific_review"),
            ]
            return {"profile": "research-reproducibility@1", "direct": parent, "initial": acquisition,
                    "followup": child, "sources": files, "checks": [
                        {"name": n, "status": "recorded", "reference": ref} for n, ref in checks],
                    "environment": {"python": platform.python_version(), "app_dependencies": "Python standard library",
                                    "dependency_lock": (ROOT/"uv.lock").read_text()},
                    "scientific_review": ["Review simulated optics and transfer to physical instruments."] +
                        ([] if child["result"]["status"] == "ok" else ["Follow-up outside calibration."])}

    def source(self, task_id):
        if self.task(task_id).get("archived"):
            return deepcopy(self.archive["sources"][task_id])
        folder = self.path(task_id)
        files = {n: (folder/n).read_text() for n in b12_build.FILES if (folder/n).is_file()}
        task = self.task(task_id)
        diff = []
        if task.get("parent_id"):
            parent = self.path(task["parent_id"])
            for name, content in files.items():
                diff.extend(difflib.unified_diff((parent/name).read_text().splitlines(True),
                                                 content.splitlines(True), "v1/"+name, "v2/"+name))
        return {"files": files, "diff": "".join(diff)}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, data, content_type="application/json", attachment=None):
        if content_type == "application/json":
            data = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, post=False):
        host = self.headers.get("Host", "")
        if host not in self.server.hosts or self.headers.get("Origin", "http://" + host) != "http://" + host:
            return self.send(403, {"error": "Local presenter requests only"})
        lab = self.server.lab
        parts = urlsplit(self.path).path.strip("/").split("/")
        try:
            if post:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("JSON content required")
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                if parts == ["api","tasks"]:
                    return self.send(202, lab.submit(body.get("brief")))
                if len(parts) == 4 and parts[:2] == ["api","tasks"]:
                    if parts[3] == "approve":
                        return self.send(202, lab.approve(parts[2]))
                    if parts[3] == "prepare":
                        return self.send(200, lab.prepare(parts[2], body))
                    if parts[3] in ("rerun", "reveal", "replay"):
                        action = {"rerun": lab.rerun, "reveal": lab.reveal, "replay": lab.replay}[parts[3]]
                        return self.send(200, action(parts[2]))
                    if parts[3] == "retry":
                        return self.send(202, lab.retry(parts[2]))
            elif parts == [""]:
                return self.send(200, Path(__file__).with_name("presenter.html").read_bytes(), "text/html; charset=utf-8")
            elif parts == ["api","tasks"]:
                return self.send(200, {"tasks": lab.history()})
            elif parts[:2] == ["api","tasks"] and len(parts) in (3,4):
                if len(parts)==3:
                    return self.send(200, lab.task(parts[2]))
                if parts[3] == "evidence":
                    return self.send(200, lab.evidence(parts[2]), attachment="evolve-b12-"+parts[2]+".json")
                if parts[3]=="source":
                    return self.send(200, lab.source(parts[2]))
            return self.send(404, {"error":"Unknown route"})
        except FileNotFoundError:
            return self.send(404, {"error":"Record unavailable"})
        except (ValueError, TypeError, KeyError, RuntimeError) as error:
            return self.send(400, {"error":str(error)})

    do_GET = dispatch

    def do_POST(self):
        self.dispatch(post=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--store", type=Path, default=ROOT/"runs"/"b12")
    args = parser.parse_args()
    serve(args.port, args.store)


def serve(port, store, *, archive=None, allow_generation=True):
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        port = server.server_port
        server.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        server.lab = Lab(store, archive=archive, allow_generation=allow_generation)
        print(f"EVOLVE presenter http://127.0.0.1:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.lab.close()


if __name__ == "__main__":
    main()
