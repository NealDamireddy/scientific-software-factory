"""WO-28 owns authorization, validation and the catalog record types."""
from contextlib import contextmanager
import json

from factory.knowledge.catalog_contract import ApprovalReceipt, CatalogRecord, RevisionPin
from factory.knowledge.catalog_domain import CatalogDomainRepository
from factory.lab_context.context_repository import canonical_json
from .db import Database


_SELECT = """SELECT r.*, a.approver, a.approved_at FROM catalog_revisions r
    LEFT JOIN catalog_approvals a USING (revision_id)
    WHERE r.lab_id=%s AND r.kind=%s"""
_STREAM = _SELECT + " AND r.record_id=%s"


def _record(row):
    pin = RevisionPin(row["lab_id"], row["kind"], row["record_id"], row["revision"],
                      row["revision_id"], row["sha256"])
    receipt = ApprovalReceipt(pin, row["approver"], row["approved_at"]) if row["approver"] is not None else None
    return CatalogRecord(pin, row["author"], row["created_at"], row["predecessor_id"], json.loads(row["payload"]), receipt)


class _CatalogTransaction:
    def __init__(self, db, params):
        self.db = db
        self.params = params

    def read(self, revision):
        if revision is None:
            row = self.db.execute(_STREAM + " ORDER BY revision DESC LIMIT 1", self.params).fetchone()
        else:
            row = self.db.execute(_STREAM + " AND revision=%s", (*self.params, revision)).fetchone()
        return _record(row) if row else None

    def history(self):
        return tuple(_record(r) for r in self.db.execute(_STREAM + " ORDER BY revision", self.params))

    def has_source(self, revision_id):
        return self.db.execute("""SELECT 1 FROM catalog_revisions
            WHERE revision_id=%s AND lab_id=%s AND kind='source'""", (revision_id, self.params[0])).fetchone() is not None

    def append(self, record, encoded):
        pin = record.pin
        self.db.execute("""INSERT INTO catalog_revisions
            (revision_id,lab_id,kind,record_id,revision,sha256,author,created_at,predecessor_id,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (pin.revision_id, *self.params, pin.revision, pin.sha256, record.author, record.created_at,
             record.predecessor_id, encoded))

    def add_receipt(self, receipt):
        self.db.execute("INSERT INTO catalog_approvals VALUES (%s,%s,%s)",
                        (receipt.pin.revision_id, receipt.approver, receipt.approved_at))


class PostgresCatalogRepository(Database, CatalogDomainRepository):
    def _read_by_id(self, kind, lab_id, revision_id):
        with self.transaction() as db:
            row = db.execute(_SELECT + " AND r.revision_id=%s", (lab_id, kind, revision_id)).fetchone()
            return _record(row) if row else None

    @contextmanager
    def _transaction(self, kind, lab_id, record_id, *, write):
        params = (lab_id, kind, record_id)
        with self.transaction() as db:
            if write:
                db.execute("SELECT pg_advisory_xact_lock(452, hashtext(%s))", (canonical_json(params),))
            yield _CatalogTransaction(db, params)
