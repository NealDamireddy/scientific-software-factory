"""Atomic verifier publication and digest-checked historical release reads."""
import json

from psycopg import sql

from factory.context import digest
from factory.software.release_repository import canonical
from .db import Database


def _verify_existing(db, table, sha, content):
    table = sql.Identifier(table)
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
                inserted = db.execute("INSERT INTO scientific_blobs VALUES (%s,%s) ON CONFLICT DO NOTHING",
                                      (sha, files[name]))
                if not inserted.rowcount:
                    _verify_existing(db, "scientific_blobs", sha, files[name])
            scope = (context["lab"]["lab_id"], context["project"]["project_id"])
            inserted = db.execute("""INSERT INTO scientific_manifests (digest,content,lab,project)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (release_id, content, *scope))
            if not inserted.rowcount:
                _verify_existing(db, "scientific_manifests", release_id, content)
            db.execute("""INSERT INTO scientific_active VALUES (%s,%s,%s,%s)
                ON CONFLICT(lab,project,experiment) DO UPDATE SET digest=excluded.digest""",
                (*scope, manifest["experiment_type"], release_id))
        return release_id

    def verified_ids(self, lab_id, project_id):
        with self.transaction() as db:
            rows = db.execute("""SELECT digest FROM scientific_manifests
                WHERE lab=%s AND project=%s ORDER BY seq DESC""", (lab_id, project_id))
            return [row["digest"] for row in rows]

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
