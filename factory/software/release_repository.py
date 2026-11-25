"""Local immutable scientific releases and project-scoped active pointers."""
from contextlib import closing
import json
import sqlite3

from factory.context import digest


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


class ReleaseRepository:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scientific_blobs (
                    digest TEXT PRIMARY KEY, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS scientific_manifests (
                    digest TEXT PRIMARY KEY, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS scientific_active (
                    lab TEXT, project TEXT, experiment TEXT, digest TEXT NOT NULL,
                    PRIMARY KEY (lab, project, experiment));
            """)

    def _publish_verified(self, manifest, files):
        """Called only by the verifier, with the exact bytes it ran."""
        content = canonical(manifest)
        release_id = digest(content)
        context = manifest["context"]
        # Same checks as the PostgreSQL repository: never store a blob under a digest
        # it does not have, or a manifest whose artifacts differ from the files given.
        if files.keys() != manifest["artifacts"].keys():
            raise ValueError("Release artifact names differ from manifest")
        for name, data in files.items():
            if digest(data) != manifest["artifacts"][name]:
                raise ValueError(f"{name} digest mismatch")
        with closing(sqlite3.connect(self.path)) as db, db:
            for name, data in files.items():
                sha = manifest["artifacts"][name]
                inserted = db.execute("INSERT OR IGNORE INTO scientific_blobs VALUES (?, ?)", (sha, data))
                if not inserted.rowcount:
                    stored, = db.execute("SELECT content FROM scientific_blobs WHERE digest=?", (sha,)).fetchone()
                    if stored != data:
                        raise ValueError(f"Stored {name} digest mismatch")
            inserted = db.execute("INSERT OR IGNORE INTO scientific_manifests VALUES (?, ?)", (release_id, content))
            if not inserted.rowcount:
                stored, = db.execute("SELECT content FROM scientific_manifests WHERE digest=?", (release_id,)).fetchone()
                if stored != content:
                    raise ValueError("Stored release manifest digest mismatch")
            db.execute("""INSERT INTO scientific_active VALUES (?, ?, ?, ?)
                          ON CONFLICT(lab, project, experiment) DO UPDATE SET digest = excluded.digest""",
                       (context["lab"]["lab_id"], context["project"]["project_id"],
                        manifest["experiment_type"], release_id))
        return release_id

    def active(self, lab_id, project_id, experiment_type):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("""SELECT digest FROM scientific_active
                                WHERE lab=? AND project=? AND experiment=?""",
                             (lab_id, project_id, experiment_type)).fetchone()
        return row[0] if row else None

    def load(self, release_id):
        """Verify the manifest and each artifact before making any source executable."""
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT content FROM scientific_manifests WHERE digest=?", (release_id,)).fetchone()
            if not row:
                raise KeyError("Unknown release")
            if digest(row[0]) != release_id:
                raise ValueError("Release manifest digest mismatch")
            manifest = json.loads(row[0])
            files = {}
            for name, sha in manifest["artifacts"].items():
                blob = db.execute("SELECT content FROM scientific_blobs WHERE digest=?", (sha,)).fetchone()
                if not blob or digest(blob[0]) != sha:
                    raise ValueError(f"{name} digest mismatch")
                files[name] = blob[0]
        return manifest, files
