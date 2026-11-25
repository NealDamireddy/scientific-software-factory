"""PostgreSQL transaction port for WO-31's shared scientific artifact queries."""
from contextlib import contextmanager

from factory.knowledge.scientific_artifact_repository import SQLScientificArtifactRepository
from .db import Database


class _ArtifactQueries:
    """The domain's fixed SQL uses qmark parameters. Values stay bound separately."""
    def __init__(self, db):
        self.db = db

    def execute(self, query, params=()):
        return self.db.execute(query.replace("?", "%s"), params)

    def executemany(self, query, params):
        with self.db.cursor() as cursor:
            cursor.executemany(query.replace("?", "%s"), params)


class PostgresScientificArtifactRepository(SQLScientificArtifactRepository):
    def __init__(self, dsn, principal):
        super().__init__(principal)
        self.database = Database(dsn)

    @contextmanager
    def transaction(self, *, write):
        with self.database.transaction() as db:
            if write:
                # Changes to a requirement and blueprints citing it reconcile in
                # either insertion order. The shared port spans artifact streams.
                db.execute("LOCK TABLE sci_artifact_revision IN SHARE ROW EXCLUSIVE MODE")
            else:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            yield _ArtifactQueries(db)
