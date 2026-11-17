"""PostgreSQL CAS append port for WO-37's shared runtime command semantics."""
import json

from ..context import digest
from ..context_repository import RevisionConflict, canonical_json
from ..runtime_work_order_domain import RuntimeWorkOrders
from .db import Database


class PostgresRuntimeRecordStore(Database):
    def read(self, scope):
        with self.transaction() as db:
            rows = db.execute("""SELECT body, sha256 FROM runtime_records
                WHERE lab_id=%s AND project_id=%s AND work_order_id=%s ORDER BY version""",
                (scope.lab_id, scope.project_id, scope.work_order_id))
            records = []
            for row in rows:
                if digest(row["body"].encode()) != row["sha256"]:
                    raise ValueError("Stored runtime work-order record digest mismatch")
                records.append(json.loads(row["body"]))
            return records

    def append(self, scope, record, *, expected_version):
        key = (scope.lab_id, scope.project_id, scope.work_order_id)
        with self.transaction() as db:
            db.execute("SELECT pg_advisory_xact_lock(453, hashtext(%s))", (canonical_json(key),))
            row = db.execute("""SELECT COALESCE(MAX(version),0) AS head FROM runtime_records
                WHERE lab_id=%s AND project_id=%s AND work_order_id=%s""", key).fetchone()
            if row["head"] != expected_version or record["version"] != expected_version + 1:
                raise RevisionConflict("Runtime work order changed; reload the stream")
            encoded = canonical_json(record)
            result = db.execute("""INSERT INTO runtime_records
                (lab_id,project_id,work_order_id,version,key,body,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING version""",
                (*key, record["version"], record["key"], encoded, digest(encoded.encode()))).fetchone()
            if result is None:
                raise RevisionConflict("Runtime command key already used")


class PostgresRuntimeWorkOrderRepository(RuntimeWorkOrders):
    def __init__(self, dsn):
        super().__init__(PostgresRuntimeRecordStore(dsn))
