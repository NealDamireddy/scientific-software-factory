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

from . import b12_build, b12_reuse
from .b12_verification import UNBOUND_VERIFICATION, verification_receipt
from .archive import validate_archive
from .context import ROOT, read_json
from .optics import PROFILE, RECIPE, validate_preparation, acquire, assess, calibration_digest, fit_calibration, validate_recipe, verify_candidate
from .sandbox import execute
from .followup import _payload, run_followup, replay_acquisition


def save(path, obj):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False))
    temporary.replace(path)


def _matches_reconstructed_evidence(recorded, reconstructed):
    """Allow one representable step of platform log10 rounding only in absorbances."""
    if not isinstance(recorded, dict) or recorded.keys() != reconstructed.keys():
        return False
    readings = recorded["absorbances"]
    expected = reconstructed["absorbances"]
    if not isinstance(readings, list) or len(readings) != len(expected):
        return False
    for value, reference in zip(readings, expected):
        lower = math.nextafter(reference, -math.inf)
        upper = math.nextafter(reference, math.inf)
        if type(value) not in (int, float) or not lower <= value <= upper:
            return False
    # Compare JSON types as well as values (in Python, True == 1).
    metadata = {key: value for key, value in recorded.items() if key != "absorbances"}
    expected_metadata = {key: value for key, value in reconstructed.items() if key != "absorbances"}
    return json.dumps(metadata, sort_keys=True) == json.dumps(expected_metadata, sort_keys=True)


class Lab:
    def __init__(self, store, *, archive=None, allow_generation=True):
        self.archive = validate_archive(archive) if archive is not None else None
        self.archived = ({task["id"]: task for task in (self.archive["direct"], self.archive["followup"])}
                         if self.archive else {})
        self.allow_generation = allow_generation
        self.store = Path(store)
        self.lease = None
        if allow_generation:
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
        if self.lease is not None:
            self.lease.close()

    def history(self):
        paths = self.store.glob("*/task.json") if self.allow_generation else ()
        live = {p.parent.name: self.task(p.parent.name) for p in paths}
        saved = [self.task(identifier) for identifier in self.archived if identifier not in live]
        return sorted([*live.values(), *saved], key=lambda r: r["created"], reverse=True)

    def path(self, task_id):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("Invalid task ID")
        if not self.allow_generation:
            raise FileNotFoundError("Live store unavailable in archive-only mode")
        folder = self.store / task_id
        if not folder.is_dir():
            raise FileNotFoundError("Task does not exist")
        return folder

    def task(self, task_id):
        if task_id in self.archived and (not self.allow_generation or not (self.store / task_id).exists()):
            return {**deepcopy(self.archived[task_id]), "mode": "previous completed run", "archived": True}
        task = read_json(self.path(task_id) / "task.json")
        if task["status"] == "verified" and not task.get("parent_id") and task.get("finding", {}).get("above_range"):
            data = read_json(self.path(task_id)/"acquisition.json")
            task["proposal"] = {
                "reason": (f"All three readings ({', '.join(format(n, '.5f') for n in task['finding']['absorbances'])}) "
                           f"exceed the strongest standard ({data['calibration']['high']:.5f}). "
                           "The protocol permits a 2× or 4× dilution followed by three fresh readings."),
                "protocol": PROFILE["protocol"], "upper_standard": data["calibration"]["high"],
                "readings": task["finding"]["absorbances"], "factors": [2, 4],
                "volumes": "One volume sample plus one (2×) or three (4×) volumes of matching solvent",
                "calibration_id": data["calibration"].get("id"),
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

    def submit(self, brief, sample_id="U-01"):
        if not isinstance(brief, str) or not 1 <= len(brief.strip()) <= 4000:
            raise ValueError("Enter a B12 request of up to 4000 characters")
        for wavelength in re.findall(r"(\d+(?:\.\d+)?)\s*(?:nm|nanomet(?:er|re)s?)\b", brief, re.I):
            if float(wavelength) != RECIPE["wavelength_nm"]:
                raise ValueError("The simulated instrument implements only the 550 nm channel")
        if (not isinstance(sample_id, str) or not 1 <= len(sample_id) <= 120
                or sample_id != sample_id.strip() or not sample_id.isprintable()):
            raise ValueError("Enter a sample ID of up to 120 printable characters")
        return self.enqueue(brief, sample_id=sample_id)

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

    def approve(self, task_id, factor=2):
        self.require_live(task_id)
        with self.lock:
            original = self.task(task_id)
            if (original.get("status") != "verified" or not original.get("proposal")
                    or original.get("parent_id") or not original.get("finding", {}).get("above_range")):
                raise ValueError("A verified direct above-range run is required")
            proposal = original["proposal"]
            if type(factor) not in (int, float) or factor not in proposal["factors"]:
                raise ValueError("Approve a protocol-supported 2× or 4× preparation")
            self.parent_source(original)
            measurement = read_json(self.path(task_id) / "acquisition.json")
            calibration = measurement["calibration"]
            sample = original.get("sample_id", "U-01")
            result = original.get("result", {})
            payload, observed = _payload(measurement["raw"], calibration, sample, None, RECIPE)
            if (calibration["instrument_profile"] != PROFILE["instrument_profile"]
                    or not observed["above_range"]
                    or not _matches_reconstructed_evidence(original["finding"], observed)
                    or not _matches_reconstructed_evidence(measurement.get("finding", observed), observed)
                    or not _matches_reconstructed_evidence(measurement["input"], payload)
                    or result.get("sample_id") != sample or result.get("status") != "review"
                    or result["concentration_mg_l"] is not None
                    or calibration_digest(calibration) != calibration.get("id")
                    or result.get("calibration_id") != calibration["id"]):
                raise ValueError("Direct sample evidence does not support this approval")
            for task in self.history():
                if (not task.get("archived") and task.get("parent_id") == task_id
                        and task.get("approval", {}).get("factor") == factor):
                    return task
            return self.enqueue(proposal["requirement"], parent_id=task_id,
                                parent_revision=original["revision"], approval={
                                    "approved_at": datetime.now(timezone.utc).isoformat(),
                                    "origin": task_id, "factor": int(factor), "protocol": proposal["protocol"],
                                    "parent_sample_id": sample,
                                    "evidence": {key: proposal[key] for key in
                                                 ("readings", "upper_standard", "calibration_id")}})

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
            if (prep["parent_id"] != task["approval"].get("parent_sample_id", "U-01")
                    or not math.isclose(factor, task["approval"]["factor"])):
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

    def parent_source(self, parent):
        origin = parent.get("origin_task_id", parent["id"])
        source = b12_reuse.read_release(self.path(origin))
        if (source["revision"] != parent["revision"]
                or b12_build.revision(self.path(parent["id"])) != source["revision"]):
            raise ValueError("Parent source digest mismatch")
        if (parent.get("context") != PROFILE or parent.get("status") != "verified"
                or parent.get("checks") != source["checks"] or parent.get("worker") != source["worker"]
                or parent.get("verification") != source["verification"]
                or parent.get("release_contract", source["release_contract"]) != source["release_contract"]):
            raise ValueError("Parent release provenance differs from the original verified source")
        if origin != parent["id"] and (parent.get("mode") != "verified source reuse"
                                       or parent.get("release_contract") != source["release_contract"]
                                       or parent.get("origin_parent_revision") != source.get("parent_revision")
                                       or parent.get("origin_parent_checks") != source.get("parent_checks")
                                       or parent.get("origin_parent_worker") != source.get("parent_worker")
                                       or parent.get("origin_parent_task_id") != source.get("parent_origin_task_id")
                                       or parent.get("origin_parent_verification") != source.get("parent_verification")):
            raise ValueError("Parent reuse provenance differs from the original verified source")
        return source

    def revise(self, task, folder, parent_source):
        parent = self.path(task["parent_id"])
        previous = verify_candidate(parent/"analysis.py", prepared=True)
        self.update(task["id"], parent_checks=previous)
        if all(case["pass"] for case in previous):
            raise ValueError("The parent already supports the requested capability")
        b12_reuse.validate_parent_checks(previous)
        receipt = b12_build.build(task["brief"], folder, parent_source["files"]["analysis.py"].decode())
        revision = b12_build.revision(folder)
        if revision == task["parent_revision"]:
            raise ValueError("The candidate has no source changes")
        self.update(task["id"], status="verifying", worker=receipt, revision=revision)
        checks = verify_candidate(folder/"analysis.py", prepared=True)
        self.update(task["id"], checks=checks)
        if not checks or not all(case["pass"] for case in checks):
            raise ValueError("Prepared-sample release failed its independent requirements")
        if b12_build.revision(folder) != revision or b12_build.revision(parent) != parent_source["revision"]:
            raise ValueError("Source changed during preparation verification")
        contract = b12_reuse.release_contract(prepared=True)
        self.update(task["id"], status="verified", views=read_json(folder/"views.json"),
                    release_contract=contract, verification=verification_receipt(revision, checks, receipt, contract),
                    parent_verification=verification_receipt(parent_source["revision"], previous,
                                                             parent_source["worker"], contract))

    def select_source(self, task, folder):
        prepared = bool(task.get("parent_id"))
        source, rejections = b12_reuse.select_release(self.store, prepared)
        self.update(task["id"], reuse_rejections=rejections)
        if source is None:
            # A prepared request has already resolved its verified direct parent.
            # It can revise that parent if the prepared capability is unavailable.
            if not prepared and any(reasons != [UNBOUND_VERIFICATION] for reasons in rejections.values()):
                raise ValueError("No compatible verified release: " + "; ".join(
                    f"{origin}: {', '.join(reasons)}" for origin, reasons in rejections.items()))
            return None
        # Persist precisely the bytes inspected during selection. Each run has its own
        # immutable copy for the existing acquisition, evidence and replay interfaces.
        for name in b12_build.FILES:
            (folder / name).write_bytes(source["files"][name])
        provenance = {}
        if source.get("parent_revision"):
            provenance = {"origin_parent_revision": source["parent_revision"],
                          "origin_parent_checks": source["parent_checks"],
                          "origin_parent_worker": source["parent_worker"],
                          "origin_parent_task_id": source["parent_origin_task_id"],
                          "origin_parent_verification": source["parent_verification"]}
        return self.update(task["id"], mode="verified source reuse", origin_task_id=source["id"],
                           revision=source["revision"], worker=source["worker"], checks=source["checks"],
                           verification=source["verification"], release_contract=source["release_contract"], **provenance)

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
            parent_source = None
            if task.get("parent_id"):
                parent_source = self.parent_source(self.task(task["parent_id"]))
                if parent_source["revision"] != task["parent_revision"]:
                    raise ValueError("Approved parent revision differs from verified source")
            reused = self.select_source(task, folder)
            if parent_source:
                if reused:
                    if (task["parent_revision"] == reused["origin_parent_revision"]
                            and parent_source["id"] == reused["origin_parent_task_id"]):
                        previous = reused["origin_parent_checks"]
                    elif "prepared" in parent_source["release_contract"]["capabilities"]:
                        previous = parent_source["checks"]
                    else:
                        previous = verify_candidate(self.path(task["parent_id"]) / "analysis.py", prepared=True)
                        b12_reuse.validate_parent_checks(previous)
                    self.update(task_id, status="verified", parent_checks=previous,
                                parent_verification=verification_receipt(parent_source["revision"], previous,
                                                                         parent_source["worker"], reused["release_contract"]),
                                views=read_json(folder / "views.json"))
                else:
                    self.revise(task, folder, parent_source)
                return
            with ThreadPoolExecutor(max_workers=1) as bench:
                acquisition = bench.submit(self.collect, task_id)
                if reused:
                    checks = reused["checks"]
                    revision = reused["revision"]
                    binding = reused["verification"]
                else:
                    receipt = b12_build.build(task["brief"], folder)
                    revision = b12_build.revision(folder)
                    self.update(task_id, status="verifying", worker=receipt, revision=revision)
                    checks = verify_candidate(folder / "analysis.py")
                    binding = verification_receipt(revision, checks, receipt, b12_reuse.release_contract(False))
            if not checks or not all(check["pass"] for check in checks):
                self.update(task_id, checks=checks)
                raise ValueError("Independent assay requirements failed")
            measurement = acquisition.result()
            if b12_build.revision(folder) != revision:
                raise ValueError("Source changed during direct verification")
            contract = reused["release_contract"] if reused else b12_reuse.release_contract(prepared=False)
            self.analyze_direct(task, folder, measurement, checks, contract, binding)
        except Exception as error:
            self.update(task_id, status="failed", error=str(error)[:1800])

    def analyze_direct(self, task, folder, measurement, checks, contract, binding):
        payload = measurement["input"]
        calibration = measurement["calibration"]
        finding = measurement["finding"]
        sample_id = task.get("sample_id", "U-01")
        if (payload.get("sample_id") != sample_id or len(measurement["raw"]) != RECIPE["replicates"]
                or any(record.get("sample_id") != sample_id for record in measurement["raw"])):
            raise ValueError("Acquisition sample ID differs from the requested sample")
        result, runtime = execute(folder / "analysis.py", json.dumps(payload).encode())
        if (result.get("sample_id") != sample_id or result.get("calibration_id") != calibration["id"]
                or result.get("status") != ("ok" if finding["in_range"] else "review")):
            raise ValueError("Actual sample result disagrees with trusted range or provenance check")
        if not finding["in_range"] and (
            "concentration_mg_l" not in result or result["concentration_mg_l"] is not None
        ):
            raise ValueError("Out-of-range result must include concentration_mg_l set to null")
        if finding["in_range"]:
            reference = (sum(finding["absorbances"])/3 - calibration["intercept"]) / calibration["slope"]
            actual = result.get("concentration_mg_l")
            if type(actual) not in (float, int) or not math.isclose(actual, reference, abs_tol=1e-7):
                raise ValueError("Actual sample concentration disagrees with the frozen calibration")
        return self.update(task["id"], status="verified", checks=checks, result=result, finding=finding,
                           sandbox=runtime, views=read_json(folder / "views.json"),
                           release_contract=contract, verification=binding)

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
                    return self.send(202, lab.submit(body.get("brief"), body.get("sample_id", "U-01")))
                if len(parts) == 4 and parts[:2] == ["api","tasks"]:
                    if parts[3] == "approve":
                        return self.send(202, lab.approve(parts[2], body.get("factor", 2)))
                    if parts[3] == "prepare":
                        return self.send(200, lab.prepare(parts[2], body))
                    if parts[3] == "rerun" and "retry_of" in body:
                        return self.send(200, lab.rerun(parts[2], retry_of=body["retry_of"]))
                    if parts[3] in ("rerun", "reveal", "replay"):
                        action = {"rerun": lab.rerun, "reveal": lab.reveal, "replay": lab.replay}[parts[3]]
                        return self.send(200, action(parts[2]))
                    if parts[3] == "retry":
                        return self.send(202, lab.retry(parts[2]))
            elif parts == [""]:
                return self.send(200, Path(__file__).with_name("presenter.html").read_bytes(), "text/html; charset=utf-8")
            elif parts == ["api","tasks"]:
                return self.send(200, {"tasks": lab.history(), "allow_generation": lab.allow_generation})
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
