"""Each operation owns a transaction. All migrations commit or roll back together."""
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn):
        self.dsn = dsn
        migrations = sorted(Path(__file__).with_name("migrations").glob("*.sql"))
        with self.transaction() as db:
            # Serializes initial schema creation by independently starting workers.
            db.execute("SELECT pg_advisory_xact_lock(8090, 45)")
            db.execute("""CREATE TABLE IF NOT EXISTS evolve_migrations
                       (version integer PRIMARY KEY)""")
            applied = [row["version"] for row in db.execute(
                "SELECT version FROM evolve_migrations ORDER BY version")]
            versions = [int(path.name.split("_")[0]) for path in migrations]
            if applied != versions[:len(applied)]:
                raise ValueError(f"Unsupported hosted database versions: {applied}")
            for path, version in zip(migrations[len(applied):], versions[len(applied):]):
                db.execute(path.read_text(encoding="utf-8"))
                db.execute("INSERT INTO evolve_migrations VALUES (%s)", (version,))

    def transaction(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)
