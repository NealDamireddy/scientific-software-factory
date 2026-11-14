"""Trusted WO-8 handoff for offline verification and release of scientific applications."""
from contextlib import ExitStack
import errno
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from .b12_build import FILES, content_revision
from .context import digest
from .release_repository import canonical
from .sandbox import execute
from .scientific_contract import TOLERANCE, case_plan, compare
from .uvvis_contract import validate_settings


TYPES = ("concentration", "time_course")
VERIFIER = "scientific-release@5"
ERRORS = (ValueError, TypeError, KeyError, RuntimeError, OSError, ArithmeticError, RecursionError, SyntaxError)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    return isinstance(value, str) and bool(value.strip())


def sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def metrics(kind):
    fields = ["calibration_id", "sample_id", "concentration_mg_l", "replicate_sd_mg_l", "review_reason"]
    return fields + (["timestamp"] if kind == "time_course" else [])


def check_context(context, profile, recipe, kind):
    # Revision metadata is projected from trusted WO-6 ContextRevision objects.
    # Approval and compiled recipe come from WO-8, separately from candidate metadata.
    lab, project = context["lab"], context["project"]
    for entity, pin in (("lab", lab), ("project", project)):
        require(pin["kind"] == entity and identifier(pin["revision_id"]) and sha(pin["sha256"])
                and type(pin["revision"]) is int and pin["revision"] > 0, f"Invalid {entity} revision")
    require(identifier(lab["lab_id"]) and project["lab_id"] == lab["lab_id"]
            and identifier(project["project_id"]) and project["lab_sha256"] == lab["sha256"]
            and type(project["lab_revision"]) is int and project["lab_revision"] == lab["revision"],
            "Project does not reference this lab revision")
    require(context["experiment_type"] == kind and sha(context["specification_sha256"])
            and context["compiled_recipe_sha256"] == digest(canonical(recipe)),
            "Missing specification pin or wrong compiled recipe digest")
    instrument = context["instrument"]
    require(identifier(instrument["instrument_id"]) and instrument["lab_id"] == lab["lab_id"]
            and profile["simulated"] is True and profile["blank_reference_required"] is True
            and instrument["profile_id"] == profile["profile_id"]
            and instrument["profile_sha256"] == digest(canonical(profile)), "Invalid instrument or profile pin")
    require(all(recipe[k] == instrument[k] for k in ("instrument_id", "profile_id", "profile_sha256")),
            "Compiled recipe has different instrument pins")
    require(type(recipe["schema_version"]) in (int, float) and recipe["schema_version"] == 1,
            "Unsupported recipe version")
    validate_settings(recipe["settings"], profile)


def check_files(files, candidate):
    require(set(files) == set(FILES), "Expected analysis.py, recipe.json and views.json")
    for name in FILES:
        require(type(files[name]) is bytes and 0 < len(files[name]) <= 65536, f"Invalid size or type for {name}")
    require({name: digest(files[name]) for name in FILES} == candidate["artifacts"], "Artifact digest mismatch")
    require(content_revision(files) == candidate["source_revision"], "Source revision mismatch")
    compile(files["analysis.py"], "analysis.py", "exec")


def check_receipt(candidate, context, kind):
    receipt = candidate["worker_receipt"]
    require(receipt["outcome"] == "completed" and identifier(receipt["method"])
            and receipt["source_revision"] == candidate["source_revision"], "Invalid worker receipt")
    require(candidate["experiment_type"] == kind and candidate["context_sha256"] == digest(canonical(context))
            and candidate["verification_contract"] == f"{kind}@1", "Candidate context or contract mismatch")


def read_artifact(data):
    require(type(data) is bytes and 0 < len(data) <= 65536, "Invalid JSON artifact size or type")

    def unique_keys(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), "Duplicate artifact key")
        return result
    return json.loads(data, object_pairs_hook=unique_keys)


def check_views(data, kind):
    views = read_artifact(data)
    require(set(views) == {"title", "metrics"} and identifier(views["title"]) and len(views["title"]) <= 160
            and isinstance(views["metrics"], list) and sorted(views["metrics"]) == sorted(metrics(kind)),
            "Display must identify each supported result field exactly once")


def isolation_probe(folder):
    # A successful sandbox launch alone does not establish the offline/read-only boundary.
    hidden, calibration, verifier = [folder / n for n in ("private-sample", "calibration", "verification")]
    for path in (hidden, calibration, verifier):
        path.write_bytes(b"trusted sentinel")
    probe = folder / "probe.py"
    probe.write_text(f"""import errno, json, socket
def denied(action, codes):
    try:
        action()
    except OSError as exc:
        return exc.errno in codes
    return False
file_errors = ({errno.EPERM}, {errno.EACCES}, {errno.ENOENT})
print(json.dumps({{
    'hidden': denied(lambda: open({str(hidden)!r}).read(), file_errors),
    'calibration': denied(lambda: open({str(calibration)!r}, 'wb'), file_errors),
    'verification': denied(lambda: open({str(verifier)!r}, 'wb'), file_errors),
    'network': denied(lambda: socket.create_connection(('192.0.2.1', 80), .5),
                      (errno.EPERM, errno.EACCES, errno.ENETUNREACH, errno.EHOSTUNREACH))
}}))
""")
    result, backend = execute(probe, b"")
    require(result == dict.fromkeys(("hidden", "calibration", "verification", "network"), True),
            f"Sandbox access probe failed: {result}")
    require(all(p.read_bytes() == b"trusted sentinel" for p in (hidden, calibration, verifier)),
            "Sandbox changed trusted data")
    return backend


def verify_release(repository, *, experiment_type, context, profile, compiled_recipe, candidate, files):
    """Evaluate a snapshot. The four trusted inputs precede worker metadata and worker bytes.

    context carries the lab/project revision headers, instrument pin, specification_sha256
    and compiled_recipe_sha256. candidate carries matching source/artifact digests, experiment
    type, context_sha256, verification_contract and the retained worker receipt.
    """
    checks = []

    def run(name, category, action, blocked_by=None):
        if blocked_by:
            status, detail = "blocked", f"Blocked by {blocked_by}"
        else:
            try:
                detail = action() or "Passed"
                status = "passed"
            except ERRORS as exc:
                status, detail = "failed", str(exc)[:400]
        checks.append(dict(name=name, category=category, status=status, passed=status == "passed", detail=detail))
        return status == "passed"

    # Snapshot all mutable caller data before verification; publication reuses these bytes.
    def snapshot():
        nonlocal context, profile, compiled_recipe, candidate, files
        context, profile, compiled_recipe, candidate = json.loads(canonical([context, profile, compiled_recipe, candidate]))
        files = dict(files)

    report = {"release_id": None, "checks": checks}
    snapped = run("handoff snapshot", "provenance", snapshot)
    snapshot_blocker = None if snapped else "handoff snapshot"
    kind = experiment_type
    supported = run("supported verification contract", "provenance",
                    lambda: require(kind in TYPES, "Unsupported experiment type"))
    pinned = run("pinned context and acquisition settings", "acquisition settings",
                 lambda: check_context(context, profile, compiled_recipe, kind), snapshot_blocker)
    artifacts = run("candidate artifact and source digests", "provenance",
                    lambda: check_files(files, candidate), snapshot_blocker)
    run("candidate worker and context", "provenance", lambda: check_receipt(candidate, context, kind), snapshot_blocker)
    run("compiled recipe equality", "acquisition settings",
        lambda: require(canonical(read_artifact(files["recipe.json"])) == canonical(compiled_recipe),
                        "Worker recipe differs from approved compiled recipe"), snapshot_blocker)
    run("display contract", "input validation", lambda: check_views(files["views.json"], kind), snapshot_blocker)

    if supported:
        blockers = [name for name, passed in (("pinned context and acquisition settings", pinned),
                                              ("candidate artifact and source digests", artifacts)) if not passed]
        prerequisite = snapshot_blocker or ", ".join(blockers)
        with ExitStack() as stack:
            def prepare_sandbox():
                nonlocal source
                folder = Path(stack.enter_context(TemporaryDirectory()))
                backend = isolation_probe(folder)
                source = folder / "analysis.py"
                source.write_bytes(files["analysis.py"])
                return backend

            source = None
            safe = run("offline sandbox and trusted files", "isolation", prepare_sandbox, prerequisite)
            case_blocker = None if safe else prerequisite or "offline sandbox and trusted files"
            for name, category, build in case_plan(kind):
                def evaluate():
                    payload, expected = build(compiled_recipe)
                    # Negative verifier fixtures deliberately include nonfinite measurement inputs.
                    actual, _ = execute(source, json.dumps(payload).encode())
                    compare(actual, expected)
                    if category == "numerical" and all(row["review_reason"] is None for row in expected["results"]):
                        return {"expected": expected, "observed": actual}
                run(name, category, evaluate, case_blocker)
    if all(item["passed"] for item in checks):
        manifest = dict(experiment_type=kind, source_revision=candidate["source_revision"],
                        artifacts=candidate["artifacts"], context=context, public_profile=profile,
                        worker_receipt=candidate["worker_receipt"], verification_contract=f"{kind}@1",
                        verifier_revision=VERIFIER, input_schema="uvvis-analysis-input@1",
                        output_schema="uvvis-analysis-output@1", rel_tol=TOLERANCE, abs_tol=TOLERANCE,
                        checks=checks)
        report["release_id"] = repository._publish_verified(manifest, files)
    return report
