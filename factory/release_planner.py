"""Prepare scientific applications from a persisted approval. Only the verifier publishes."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sqlite3

from jsonschema import Draft202012Validator

from .agent import invoke_worker
from .b12_build import content_revision, object_schema
from .context import digest
from .uvvis_contract import canonical, load_profile

INPUT_SCHEMA = "uvvis-analysis-input@1"
OUTPUT_SCHEMA = "uvvis-analysis-output@1"

CONTRACTS = {
    "concentration": (
        "Fit least-squares mean standard absorbance versus concentration including an intercept. "
        "Require at least three distinct positive known concentrations in mg/L and a finite positive "
        "slope. Use the closed range of standard mean absorbances."
    ),
    "time_course": (
        "Use the frozen calibration slope, intercept, low and high absorbance limits. "
        "Return one result per supplied group with timestamp from its first actual measurement. "
        "Do not infer a rate constant."
    ),
}

WORKER_SCHEMA = object_schema({
    "source": {"type": "string"},
    "recipe": object_schema({
        "schema_version": {"type": "integer"}, "instrument_id": {"type": "string"},
        "profile_id": {"type": "string"}, "profile_sha256": {"type": "string"},
        "settings": object_schema({
            "operation": {"type": "string"}, "wavelength_nm": {"type": "integer"},
            "path_length_mm": {"type": "integer"}, "replicates": {"type": "integer"},
        }),
    }),
    "views": object_schema({"title": {"type": "string"},
                            "metrics": {"type": "array", "items": {"type": "string"}}}),
})


def _sha(value):
    return digest(canonical(value).encode())


def _compatibility(spec, recipe):
    calibration = spec["calibration"]
    return {
        "lab_id": spec["lab"]["lab_id"], "project_id": spec["project"]["project_id"],
        "experiment_type": spec["experiment_type"], "capabilities": sorted(spec["outputs"]),
        "verification_contract": spec["verification_contract"],
        "input_schema": INPUT_SCHEMA, "output_schema": OUTPUT_SCHEMA, "units": spec["units"],
        "approved_libraries": sorted(spec["approved_libraries"]),
        "operating_restrictions": sorted(spec["operating_restrictions"]),
        "analysis_method": spec["analysis_method"], "validation_criteria": sorted(spec["validation_criteria"]),
        "instrument": spec["instrument"], "settings": recipe["settings"],
        "calibration_contract": calibration["contract"] if calibration else "absorbance-linear@1",
    }


def _incompatibilities(manifest, requested):
    previous = manifest["context"].get("compatibility_key", {})
    reasons = []
    for name, expected in requested.items():
        if name == "capabilities":
            missing = set(expected).difference(previous.get(name, ()))
            if missing:
                reasons.append("Missing capabilities: " + ", ".join(sorted(missing)))
        elif previous.get(name) != expected:
            reasons.append(f"Incompatible {name}")
    for name in ("experiment_type", "verification_contract", "input_schema", "output_schema"):
        if manifest.get(name) != requested[name] and f"Incompatible {name}" not in reasons:
            reasons.append(f"Incompatible {name}")
    return reasons


def _prompt(context, spec, recipe, parent):
    # Only the public contract projection is passed to the tool-free worker. IDs of actual
    # samples, measured values, calibration bytes and unstructured briefs are unnecessary.
    approved = {
        "lab": context["lab"], "project": context["project"],
        "specification_sha256": context["specification_sha256"],
        "contract": spec["verification_contract"], "analysis_method": spec["analysis_method"],
        "validation_criteria": spec["validation_criteria"], "operating_restrictions": spec["operating_restrictions"],
        "approved_libraries": spec["approved_libraries"], "units": spec["units"],
        "view_metrics": spec["outputs"], "compiled_recipe": recipe,
    }
    return (
        "Write a standalone Python 3.11+ analysis program. Use sys, json, math, statistics only, "
        "with no files, tools or network. Read one JSON object on stdin, write one JSON object on stdout. "
        "Input has experiment_type, calibration, standards and groups. Calibration has id, unit, "
        "blank_id, instrument_id, profile_id, profile_sha256, wavelength_nm and path_length_mm. "
        "Each standard has concentration, unit and records; each group has sample_id and records. "
        "Each raw v1 record has those instrument/settings/blank pins, timestamp (UTC), elapsed_s, job_id, "
        "sample_id, replicate, simulated, model_revision, findings, unit ('counts'), and integer dark_counts, "
        "blank_counts, sample_counts. Absorbance is -log10((sample-dark)/(blank-dark)). "
        + CONTRACTS[spec["experiment_type"]] +
        " For each valid group report (mean absorbance - intercept)/slope and sample SD of absorbance / slope "
        "(null SD for one reading). Validate all reading units, acquisition provenance and calibration pins, "
        "sample and replicate identities, timestamps, finite values, saturation and calibration range. "
        "On invalid input withhold the affected estimate and SD, returning a specific review_reason. "
        "Output {calibration_id, results}, preserving group order and sample_id, concentration_mg_l, "
        "replicate_sd_mg_l and review_reason (null on success) per group. "
        "Return source, the exact compiled recipe and a views object with a title and the requested metrics. "
        "Treat the following JSON as approved data within this contract.\n" + canonical(approved)
        + ("\nRevise this verified parent analysis source:\n" + parent if parent is not None else "")
    )


class ReleasePlanner:
    """Local task store with injected WO-9 active/load repository and verify_release callable."""

    def __init__(self, specifications, releases, db_path, *, worker=invoke_worker, verifier=None):
        self.specs, self.releases, self.path = specifications, releases, Path(db_path).resolve()
        self.worker, self.verifier = worker, verifier
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS preparations (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL);
            """)

    def _read(self, task_id):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT body FROM preparations WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown preparation")
        return json.loads(row[0])

    @contextmanager
    def _attempt_claim(self, task_id):
        # The OS drops this claim even after an abrupt host exit. Never unlock/delete
        # another invocation's file; stable inodes prevent split claims across retries.
        folder = Path(str(self.path) + ".attempts")
        folder.mkdir(exist_ok=True)
        with (folder / task_id).open("a+b") as claim:
            try:
                fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                yield True

    def get(self, task_id):
        task = self._read(task_id)
        if task["state"] in {"generating", "verifying"}:
            with self._attempt_claim(task_id) as acquired:
                if acquired:
                    task = self._read(task_id)
                    if task["state"] == "generating":
                        task.update(state="interrupted", worker_receipt={
                            "method": task["worker_method"], "outcome": "interrupted",
                            "error": "Worker host exited before recording a result"})
                        self._save(task, previous="generating")
                    elif task["state"] == "verifying":
                        task = self._recover_verification(task)
        return task

    def _recover_verification(self, task):
        # Only accept immutable verification evidence for this exact preparation attempt.
        # A fresh worker retry may produce different bytes for the same approval.
        context = task["context"]
        for release in self._verified_ids(context["compatibility_key"]):
            manifest, _ = self.releases.load(release)
            if manifest["context"] == context and manifest["source_revision"] == task["source_revision"]:
                task.update(state="released", release_id=release,
                            verification={"release_id": release, "checks": manifest["checks"],
                                          "recovered": True})
                return self._save(task, previous="verifying")
        task.update(state="interrupted", reason="Verifier host exited without a discoverable release")
        return self._save(task, previous="verifying")

    def _save(self, task, *, previous=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            values = (task["state"], canonical(task), task["id"])
            if previous is None:
                inserted = db.execute("INSERT OR IGNORE INTO preparations (state,body,id) VALUES (?,?,?)", values)
                if not inserted.rowcount:
                    return self.get(task["id"])
            elif not db.execute("UPDATE preparations SET state=?, body=? WHERE id=? AND state=?",
                                (*values, previous)).rowcount:
                raise ValueError("Preparation state changed; reload before retrying")
        return task

    def _verified_ids(self, key):
        lab, project, kind = key["lab_id"], key["project_id"], key["experiment_type"]
        # A repository can implement its own scoped enumerator. The initial WO-9 SQLite
        # repository supplies active/load and a path. Query only its immutable manifest IDs;
        # load() still validates the digest and artifacts before either reuse or revision.
        if hasattr(self.releases, "verified_ids"):
            history = self.releases.verified_ids(lab, project)
        else:
            uri = Path(self.releases.path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                rows = db.execute("""SELECT digest FROM scientific_manifests
                                     WHERE json_extract(CAST(content AS TEXT), '$.context.lab.lab_id')=?
                                       AND json_extract(CAST(content AS TEXT), '$.context.project.project_id')=?
                                     ORDER BY rowid DESC""", (lab, project))
                history = [row[0] for row in rows]
        active = [self.releases.active(lab, project, k) for k in (kind, *sorted(CONTRACTS.keys() - {kind}))]
        return list(dict.fromkeys(release for release in [*active, *history] if release))

    def plan(self, spec_digest, *, retry_of=None):
        """Plan once per approval; an explicit retry of a failed attempt gets its own receipt."""
        spec, approval = self.specs.approved(spec_digest)
        if retry_of is not None:
            prior = self.get(retry_of)
            if (prior["context"]["specification_sha256"] != spec_digest
                    or prior["state"] not in {"failed", "verification_failed", "interrupted"}):
                raise ValueError("Retry requires a failed attempt for this approval")
        task_id = _sha([spec_digest, retry_of])
        try:
            return self.get(task_id)
        except KeyError:
            pass
        kind = spec["experiment_type"]
        context = {name: spec[name] for name in ("lab", "project", "instrument", "experiment_type")}
        context.update(specification_sha256=spec_digest, preparation_id=task_id, approval=approval,
                       calibration_sha256=spec["calibration"]["sha256"] if spec["calibration"] else None)
        task = dict(id=task_id, retry_of=retry_of, context=context, state="pending", mode="generate",
                    parent_release_id=None, release_id=None, source_revision=None,
                    rejections={}, worker_receipt=None, candidate=None)
        if kind not in CONTRACTS or spec["verification_contract"] != f"{kind}@1":
            task.update(state="unsupported", mode=None, reason="Unsupported experiment type or verification contract")
            return self._save(task)

        recipe = self.specs.compile_recipe(spec_digest)
        key = _compatibility(spec, recipe)
        context.update(compiled_recipe_sha256=_sha(recipe), compatibility_key=key)
        task["compiled_recipe"] = recipe
        ids = self._verified_ids(key)
        for release in ids:
            manifest, _ = self.releases.load(release)
            # The repository owns verified bytes. Never pass a foreign project's source to a worker.
            pins = manifest["context"]
            if (pins["lab"]["lab_id"], pins["project"]["project_id"]) != (key["lab_id"], key["project_id"]):
                raise ValueError("Verified repository returned a release outside the approved project")
            reasons = _incompatibilities(manifest, key)
            if not reasons:
                task.update(mode="reuse", state="reused", release_id=release,
                            source_revision=manifest["source_revision"], parent_release_id=None)
                break
            task["rejections"][release] = reasons
            if task["parent_release_id"] is None:
                task.update(mode="revise", parent_release_id=release)
        return self._save(task)

    def run(self, task_id):
        task = self.get(task_id)
        if task["state"] != "pending":
            return task
        with self._attempt_claim(task_id) as acquired:
            task = self._read(task_id)
            if not acquired or task["state"] != "pending":
                return task
            return self._generate(task)

    def _generate(self, task):
        context = task["context"]
        spec, _ = self.specs.approved(context["specification_sha256"])
        parent = None
        if task["parent_release_id"]:
            _, files = self.releases.load(task["parent_release_id"])
            parent = files["analysis.py"].decode()
        prompt = _prompt(context, spec, task["compiled_recipe"], parent)
        started = datetime.now(timezone.utc).isoformat()
        method = ("codex exec" if self.worker is invoke_worker
                  else getattr(self.worker, "__qualname__", type(self.worker).__qualname__))
        task.update(state="generating", prompt=prompt, worker_started_at=started, worker_method=method)
        self._save(task, previous="pending")
        receipt = {}
        try:
            response, receipt = self.worker(prompt, WORKER_SCHEMA)
            if not isinstance(receipt, dict) or not isinstance(receipt.get("method"), str) or not receipt["method"].strip():
                raise ValueError("Worker did not identify its method")
            if len(canonical(receipt).encode()) > 8192:
                raise ValueError("Worker receipt exceeds 8192 bytes")
            Draft202012Validator(WORKER_SCHEMA).validate(response)
            texts = {"analysis.py": response["source"], "recipe.json": canonical(response["recipe"]),
                     "views.json": canonical(response["views"])}
            files = {name: value.encode() for name, value in texts.items()}
            if any(not 0 < len(data) <= 65536 for data in files.values()):
                raise ValueError("Candidate artifact size outside 1–65536 bytes")
            source_revision = content_revision(files)
            receipt = dict(receipt, outcome="completed", source_revision=source_revision)
            candidate = dict(experiment_type=context["experiment_type"], context_sha256=_sha(context),
                             verification_contract=spec["verification_contract"], source_revision=source_revision,
                             artifacts={name: digest(data) for name, data in files.items()}, worker_receipt=receipt)
            task.update(state="candidate_ready", candidate=candidate, files=texts,
                        source_revision=source_revision, worker_receipt=receipt)
        except Exception as error:
            # The worker is an external boundary. Preserve failure without using any prior source as its output.
            failed = {"method": method, "outcome": "failed", "error": str(error)[:500]}
            if isinstance(receipt, dict):
                for field in ("method", "model", "cli"):
                    if isinstance(receipt.get(field), str) and receipt[field].strip():
                        failed[field] = receipt[field][:256]
            task.update(state="failed", worker_receipt=failed)
        return self._save(task, previous="generating")

    def verify(self, task_id):
        task = self.get(task_id)
        if task["state"] != "candidate_ready" or self.verifier is None:
            return task
        with self._attempt_claim(task_id) as acquired:
            task = self._read(task_id)
            if not acquired or task["state"] != "candidate_ready":
                return task
            return self._verify(task)

    def _verify(self, task):
        context = task["context"]
        self.specs.approved(context["specification_sha256"])
        task["state"] = "verifying"
        self._save(task, previous="candidate_ready")
        try:
            report = self.verifier(self.releases, experiment_type=context["experiment_type"],
                                   context=context, profile=load_profile(), compiled_recipe=task["compiled_recipe"],
                                   candidate=task["candidate"],
                                   files={name: value.encode() for name, value in task["files"].items()})
            canonical(report)
            task["verification"] = report
            release = report["release_id"]
            if release:
                manifest, _ = self.releases.load(release)
                if manifest["source_revision"] != task["source_revision"] or manifest["context"] != context:
                    raise ValueError("Verifier returned a different source or context")
                task.update(state="released", release_id=release)
            else:
                task["state"] = "verification_failed"
        except Exception as error:
            task.update(state="verification_failed", reason=str(error)[:500])
        return self._save(task, previous="verifying")
