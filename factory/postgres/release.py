"""Atomic verifier publication and digest-checked historical release reads."""
import json

from psycopg import sql

from ..context import digest
from ..release_repository import canonical
from .db import Database


def _put(db, table, sha, content):
    table = sql.Identifier(table)
    db.execute(sql.SQL("INSERT INTO {} VALUES (%s,%s) ON CONFLICT DO NOTHING").format(table),
               (sha, content))
    row = db.execute(sql.SQL("SELECT content FROM {} WHERE digest=%s").format(table), (sha,)).fetchone()
    if row["content"] != content:
        raise ValueError("Stored release content digest mismatch")


class PostgresReleaseRepository(Database):
    def _publish_verified(self, manifest, files):
        content = canonical(manifest)
        release_id = digest(content)
        context = manifest["context"]
        if files.keys() != manifest["artifacts"].keys():
            raise ValueError("Release artifact names differ from manifest")
        with self.transaction() as db:
            # Consistent lock order for concurrently published, overlapping blobs.
            for name in sorted(files, key=manifest["artifacts"].get):
                sha = manifest["artifacts"][name]
                if digest(files[name]) != sha:
                    raise ValueError(f"{name} digest mismatch")
                _put(db, "scientific_blobs", sha, files[name])
            _put(db, "scientific_manifests", release_id, content)
            db.execute("""INSERT INTO scientific_active VALUES (%s,%s,%s,%s)
                ON CONFLICT(lab,project,experiment) DO UPDATE SET digest=excluded.digest""",
                (context["lab"]["lab_id"], context["project"]["project_id"], manifest["experiment_type"], release_id))
        return release_id

    def active(self, lab_id, project_id, experiment_type):
        with self.transaction() as db:
            row = db.execute("SELECT digest FROM scientific_active WHERE lab=%s AND project=%s AND experiment=%s",
                             (lab_id, project_id, experiment_type)).fetchone()
            return row["digest"] if row else None

    def load(self, release_id):
        with self.transaction() as db:
            row = db.execute("SELECT content FROM scientific_manifests WHERE digest=%s", (release_id,)).fetchone()
            if row is None:
                raise KeyError("Unknown release")
            if digest(row["content"]) != release_id:
                raise ValueError("Release manifest digest mismatch")
            manifest = json.loads(row["content"])
            files = {}
            for name, sha in manifest["artifacts"].items():
                row = db.execute("SELECT content FROM scientific_blobs WHERE digest=%s", (sha,)).fetchone()
                if row is None or digest(row["content"]) != sha:
                    raise ValueError(f"{name} digest mismatch")
                files[name] = row["content"]
            return manifest, files
