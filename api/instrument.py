"""Online B12 demonstration instrument. POST a released application and a vial."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
from uuid import uuid4

from factory.hosted_assay import compile_assay
from factory.optics import acquire, assess, calibration_digest, validate_preparation

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads((ROOT / "public/b12/completed.json").read_text())
CALIBRATION = BUNDLE["initial"]["calibration"]
VIALS = {"A": 12.0, "B": 32.0}
if calibration_digest(CALIBRATION) != CALIBRATION["id"]:
    raise RuntimeError("Bundled calibration failed its integrity check")


def measure(request):
    if not isinstance(request, dict):
        raise ValueError("Expected an application and vial")
    if "expression" in request:
        compiled = compile_assay(request.get("spec"), request["expression"], CALIBRATION)
        if (request.get("revision") != compiled["revision"] or request.get("files") != compiled["files"]
                or request.get("vial") != "A"):
            raise ValueError("Generate the application before running it.")
        return read_vial(compiled["revision"], compiled["files"], "A", "vial-A", str(uuid4()))
    release = next((BUNDLE[key] for key in ("direct", "followup")
                    if BUNDLE[key]["revision"] == request.get("revision")), None)
    if release is None:
        raise ValueError("Select a released application")
    files = request.get("files")
    if files != BUNDLE["sources"][release["id"]]["files"]:
        raise ValueError("Application files differ from the released revision")
    vial = request.get("vial")
    if not isinstance(vial, str) or vial not in VIALS:
        raise ValueError("Unknown simulated vial")
    run_id = str(uuid4())
    parent = "vial-" + vial
    sample_id, preparation, factor = parent, None, 1
    if release["id"] == BUNDLE["followup"]["id"]:
        sample_id = parent + "-2x"
        preparation = {"id": "prep-" + run_id, "parent_id": parent, "sample_ml": 1,
                       "final_ml": 2, "unit": "mL"}
        factor = validate_preparation(sample_id, preparation)
    return read_vial(release["revision"], files, vial, sample_id, run_id, preparation, factor)


def read_vial(revision, files, vial, sample_id, run_id, preparation=None, factor=1):
    recipe = json.loads(files["recipe.json"])
    raw = acquire(recipe, VIALS[vial] / factor, secrets.randbits(64), sample_id=sample_id)
    readings = assess(raw, CALIBRATION)
    calibration = {k: CALIBRATION[k] for k in ("id", "slope", "intercept", "low", "high")}
    return {"run_id": run_id, "instrument": "osms-sim@1", "revision": revision,
            "source_sha256": sha256(files["analysis.py"].encode()).hexdigest(),
            "recipe": recipe, "raw": raw,
            "analysis_input": {"sample_id": sample_id, "preparation": preparation,
                               "absorbances": readings["absorbances"], "calibration": calibration}}


class handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 32768:
                return self.reply(413, {"error": "Expected an application request under 32 KiB"})
            result = measure(json.loads(self.rfile.read(size)))
        except (ValueError, TypeError, SyntaxError, ArithmeticError):
            return self.reply(400, {"error": "Invalid vial or released application package"})
        self.reply(200, result)
