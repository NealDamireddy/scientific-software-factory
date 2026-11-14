"""Capture the historical store from a checkout of the pinned base.

From any working directory, with the project dependencies and a supported offline sandbox:
    python /path/to/this/capture.py /path/to/ae7d2f3/checkout > /tmp/ae7d2f3.sql.gz

Approvals have fresh IDs and timestamps, so a recapture has different release digests.
The upgrade test reads the identities from the historical records themselves.
"""
from contextlib import closing
import gzip
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory


BASE = "ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08"


def capture(root):
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    if head != BASE or status:
        raise ValueError(f"Capture needs a clean checkout of {BASE}")
    sys.path.insert(0, str(root))
    from factory.context_repository import SQLiteContextRepository
    from factory.release_repository import ReleaseRepository
    from factory.specifications import ExperimentSpecificationService
    from scripts.check_wo8_wo9_handoff import exercise
    from tests.test_context_repository import load_demo

    with TemporaryDirectory() as folder:
        path = Path(folder) / "application.sqlite"
        contexts = SQLiteContextRepository(path)
        lab, project = load_demo(contexts)
        specs = ExperimentSpecificationService(contexts, path)
        releases = ReleaseRepository(path)
        for kind in ("concentration", "time_course"):
            report = exercise(root, path, kind, specs, releases, lab, project)
            if not report["passed"] or releases.load(report["release_id"])[0]["verifier_revision"] != "scientific-release@5":
                raise RuntimeError(f"Base handoff failed for {kind}: {report}")
        with closing(sqlite3.connect(path)) as db:
            # SQLite's logical dump omits the context repository's migration version.
            version, = db.execute("PRAGMA user_version").fetchone()
            sql = "\n".join([*db.iterdump(), f"PRAGMA user_version = {version};"]).encode()
        sys.stdout.buffer.write(gzip.compress(sql, mtime=0))


if __name__ == "__main__":
    capture(Path(sys.argv[1]).resolve())
