"""Local operator commands for Lab Factory."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .artifacts import KINDS, Procedure, parse_artifact, render_procedure, render_run_plan
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

    wo = groups.add_parser("wo", help="manage and review work orders").add_subparsers(dest="command", required=True)
    create = wo.add_parser("create")
    create.add_argument("experiment_id")
    create.add_argument("--kind", choices=KINDS, required=True)
    create.add_argument("--objective", required=True)
    wo.add_parser("list").add_argument("--status")
    wo.add_parser("show").add_argument("id")
    for decision in ("approve", "reject"):
        review = wo.add_parser(decision)
        review.add_argument("id")
        review.add_argument("--submission", type=int, required=True)
        review.add_argument("--by", required=True, metavar="NAME")
        if decision == "reject":
            review.add_argument("--reason", required=True)
    groups.add_parser("serve", help="serve the four agent tools over stdio")
    return parser


def _one_line(text: str) -> str:
    return text if text.isprintable() or not text else repr(text)


def _show(orders: WorkOrders, id: str) -> str:
    # Read one consistent view even when a claim or review occurs concurrently.
    with orders.store.read_transaction():
        order = orders.get(id)
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
    for submission in submissions:
        verdict = "passed" if submission.passed else "failed"
        lines.append(
            f"submission {submission.number} by {submission.worker} · digest {submission.artifact_digest[:12]} · {verdict}"
        )
        for result in submission.results:
            mark = "pass" if result.passed else "FAIL"
            lines.append(f"  {mark}  {result.name}: {_one_line(result.detail)}")
        artifact = parse_artifact(order.kind, submission.artifact)
        lines.append(render_procedure(artifact) if isinstance(artifact, Procedure) else render_run_plan(artifact))

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
    elif args.command == "approve":
        order = orders.approve(args.id, args.by, args.submission)
        print(f"{order.id} released: submission {args.submission} by {args.by}")
    elif args.command == "reject":
        order = orders.reject(args.id, args.by, args.submission, args.reason)
        print(f"{order.id} reopened: rejected submission {args.submission} by {args.by}")


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
