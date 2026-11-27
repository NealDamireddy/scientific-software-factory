"""Reviewer reads of registered experiments and the exact context used by an order."""

import re

from . import b12_service, honey_service, tabular_service
from .context import to_dict
from .workorders import WorkOrders


def _is_generated(experiment_id, lab_id):
    """Keep analysis demos, upload placeholders and catalog briefs in their own workflows."""
    if experiment_id in (b12_service.EXPERIMENT_ID, honey_service.EXPERIMENT_ID):
        return True
    if lab_id == tabular_service.LAB.id:
        return re.fullmatch(r"tabular-[0-9a-f]{32}", experiment_id) is not None
    return (re.fullmatch(r"reference-lab-[0-9a-f]{64}", lab_id) is not None
            and re.fullmatch(r"reference-experiment-[0-9a-f]{64}", experiment_id) is not None)


def list_experiments(store):
    # Project only summary fields. A single protocol can contain large documents.
    rows = store.connection.execute("""
        SELECT r.id, json_extract(r.body, '$.title') AS title,
               json_extract(r.body, '$.lab_id') AS lab_id, r.number AS revision
          FROM records r
          JOIN (SELECT id, MAX(number) AS latest FROM records
                 WHERE kind='experiment' GROUP BY id) heads
            ON heads.id=r.id AND heads.latest=r.number
         WHERE r.kind='experiment' ORDER BY title COLLATE NOCASE, r.id
    """)
    return {"experiments": [dict(row) for row in rows if not _is_generated(row["id"], row["lab_id"])]}


def _context(store, experiment_id, experiment_revision=None, lab_revision=None):
    experiment, exp_rev = store.get_experiment(experiment_id, experiment_revision)
    lab, lab_rev = store.get_lab(experiment.lab_id, lab_revision)
    return {"experiment": to_dict(experiment), "experiment_revision": exp_rev.number,
            "lab": to_dict(lab), "lab_revision": lab_rev.number}


def experiment_detail(store, experiment_id):
    with store.read_transaction():
        context = _context(store, experiment_id)
        procedures = store.connection.execute("""
            SELECT * FROM work_orders WHERE experiment_id=? AND kind='procedure' ORDER BY rowid DESC
        """, (experiment_id,))
        analyses = store.connection.execute("""
            SELECT a.id, p.id AS procedure_order_id, a.status
              FROM tabular_intakes i
              JOIN work_orders a ON a.id=i.work_order_id
              JOIN work_orders p ON p.id=json_extract(i.profile, '$.procedure.order_id')
             WHERE p.experiment_id=? AND p.kind='procedure' AND a.kind='analysis_app'
             ORDER BY a.rowid DESC
        """, (experiment_id,))
        return {**context, "orders": [dict(row) for row in procedures], "analyses": [dict(row) for row in analyses]}


def order_context(store, order_id):
    with store.read_transaction():
        order = WorkOrders(store).get(order_id)
        return _context(store, order.experiment_id, order.experiment_revision, order.lab_revision)
