"""Local operator commands for Lab Factory."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .artifacts import KINDS, render_artifact
from .context import ContextError, experiment_from_dict, lab_from_dict, unique_fields
from .store import NotFound, Store
from .workorders import WorkOrderError, WorkOrders


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labfactory", description="Local lab context and work orders")
    parser.add_argument("--db", default="labfactory.db", metavar="PATH", help="SQLite database path")
    groups = parser.add_subparsers(dest="group", required=True)
    for record in ("lab", "experiment"):
        commands = groups.add_parser(record).add_subparsers(dest="command", required=True)
        commands.add_parser("put", help=f"save a revision of a {record} record").add_argument("file", type=Path)

    draft = groups.add_parser("draft", help="draft a procedure from a saved goal").add_subparsers(dest="command", required=True)
    draft.add_parser("start").add_argument("experiment_id")
    draft.add_parser("demo")
    source = draft.add_parser("source", help="answer a pending method question in a fresh pinned order")
    source.add_argument("id")
    source.add_argument("--title", required=True)
    source.add_argument("--file", type=Path, required=True)
    draft.add_parser("demo-source").add_argument("id")

    wo = groups.add_parser("wo", help="manage and review work orders").add_subparsers(dest="command", required=True)
    create = wo.add_parser("create")
    create.add_argument("experiment_id")
    create.add_argument("--kind", choices=KINDS, required=True)
    create.add_argument("--objective", required=True)
    wo.add_parser("list").add_argument("--status")
    wo.add_parser("show").add_argument("id")
    citation = wo.add_parser("citation", help="show a document from the pinned context")
    citation.add_argument("order", metavar="ORDER")
    citation.add_argument("document_id", metavar="DOCUMENT_ID")
    for decision in ("approve", "reject"):
        review = wo.add_parser(decision)
        review.add_argument("id")
        review.add_argument("--submission", type=int, required=True)
        review.add_argument("--by", required=True, metavar="NAME")
        if decision == "reject":
            review.add_argument("--reason", required=True)
    requeue = wo.add_parser("requeue")
    requeue.add_argument("id")
    requeue.add_argument("--claim", type=int, required=True, metavar="CLAIM_ID")
    requeue.add_argument("--by", required=True, metavar="REVIEWER")
    requeue.add_argument("--reason", required=True, metavar="TEXT")
    groups.add_parser("serve", help="serve the four agent tools over stdio")
    return parser


def _one_line(text: str) -> str:
    return text if text.isprintable() or not text else repr(text)


def _show(orders: WorkOrders, id: str) -> str:
    # Read one consistent view even when a claim or review occurs concurrently.
    with orders.store.read_transaction():
        order = orders.get(id)
        claim_id = orders.active_claim_id(order)
        submissions = orders.submissions(id)
        history = orders.history(id)
    lines = [
        f"{order.id} {order.kind} {order.status}",
        f"experiment {order.experiment_id} revision {order.experiment_revision} · "
        f"lab {order.lab_id} revision {order.lab_revision}",
        f"objective: {_one_line(order.objective)}",
    ]
    if order.worker is not None:
        lines.append(f"worker: {order.worker}")
    if claim_id is not None:
        lines.append(f"claim: {claim_id}")
    for submission in submissions:
        verdict = "passed" if submission.passed else "failed"
        lines.append(
            f"submission {submission.number} by {submission.worker} · digest {submission.artifact_digest[:12]} · {verdict}"
        )
        for result in submission.results:
            mark = "pass" if result.passed else "FAIL"
            lines.append(f"  {mark}  {result.name}: {_one_line(result.detail)}")
        lines.append(render_artifact(order.kind, submission.artifact, experiment_id=order.experiment_id))

    if order.status == "in_review":
        lines.append(f"awaiting review: submission {submissions[-1].number}")
    if order.status == "released":
        decision = next(e for e in history if e["event"] == "approved")
        lines.append(f"released: submission {order.released_submission} by {decision['actor']}")
    lines.append("history")
    for event in history:
        entry = f"  {event['at']} {event['event']} by {event['actor']}"
        if event["submission"] is not None:
            entry += f" · submission {event['submission']}"
        if event["note"]:
            entry += f" · {_one_line(event['note'])}"
        lines.append(entry)
    return "\n".join(lines)


def _operate(args, store: Store) -> None:
    if args.group == "draft":
        from . import procedure_demo, procedure_drafts
        if args.command == "start":
            print(procedure_drafts.create(store, args.experiment_id, "operator").id)
        elif args.command == "demo":
            print(procedure_demo.start(store, "operator"))
        elif args.command == "demo-source":
            if not (procedure_drafts.info(store, args.id) or {}).get("demo"):
                raise WorkOrderError("Choose a teaching demo order.")
            print(procedure_drafts.add_source(store, args.id, "operator", None, None))
        else:
            print(procedure_drafts.add_source(store, args.id, "operator", args.title, args.file.read_text(encoding="utf-8")))
        return
    if args.group in ("lab", "experiment"):
        data = json.loads(args.file.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
        if args.group == "lab":
            record = lab_from_dict(data)
            revision = store.put_lab(record)
        else:
            record = experiment_from_dict(data)
            revision = store.put_experiment(record)
        print(f"{record.id} revision {revision.number}")
        return

    orders = WorkOrders(store)
    if args.command == "create":
        print(orders.create(args.experiment_id, args.kind, args.objective).id)
    elif args.command == "list":
        for order in orders.list(args.status):
            print(f"{order.id} {order.kind} {order.status} · {_one_line(order.objective)}")
    elif args.command == "show":
        print(_show(orders, args.id))
    elif args.command == "citation":
        citation = orders.citation(args.order, args.document_id)
        document = citation.document
        print(f"{citation.origin} {citation.record_id} revision {citation.revision}")
        print(f"document: {_one_line(document.id)}")
        print(f"kind: {document.kind}")
        print(f"title: {_one_line(document.title)}")
        print(f"source: {_one_line(document.source)}")
        print()
        sys.stdout.write(document.text)
    elif args.command == "approve":
        order = orders.approve(args.id, args.by, args.submission)
        print(f"{order.id} released: submission {args.submission} by {args.by}")
    elif args.command == "reject":
        order = orders.reject(args.id, args.by, args.submission, args.reason)
        print(f"{order.id} reopened: rejected submission {args.submission} by {args.by}")
    elif args.command == "requeue":
        order = orders.requeue(args.id, args.by, args.claim, args.reason)
        print(f"{order.id} requeued: claim {args.claim} by {args.by}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.group == "serve":
            from .mcp_server import build_server

            build_server(args.db).run(transport="stdio")
        else:
            with Store(args.db) as store:
                _operate(args, store)
    except (ContextError, NotFound, WorkOrderError, OSError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        print(f"error: {_one_line(str(exc))}", file=sys.stderr)
        return 1
    return 0
