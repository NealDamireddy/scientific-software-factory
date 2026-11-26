"""Independent local queue durability, lease, retry, and concurrency checks."""

import multiprocessing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time


def _packet(db, op, **fields):
    return {
        "db": str(db), "op": op, "job": "display-1", "worker": "author-A",
        "now": 100, "ttl": 5, "key": "request-A", "token": "", "payload": "input bytes",
        **fields,
    }


def _ok(response, expected=True):
    if not isinstance(response, dict) or response.get("ok") is not expected:
        raise ValueError(f"expected ok={expected}; got {response!r}")
    return response


def _row(solve, db, status, result=None, **fields):
    row = _ok(solve(_packet(db, "read", **fields)))
    if row.get("status") != status or row.get("result") != result:
        raise ValueError(f"expected state {status!r} and result {result!r}; got {row!r}")


def _enqueue(solve, db):
    return _ok(solve(_packet(db, "enqueue")))


def _lease(solve, db, **fields):
    result = _ok(solve(_packet(db, "lease", **fields)))
    token = result.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("a lease must issue a nonempty token")
    return token


def _deliver(solve, packet, barrier, writer):
    try:
        if barrier is not None:
            barrier.wait(timeout=10)
        writer.send((True, solve(packet)))
    except Exception as exc:
        writer.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        writer.close()


def _independent(solve, packets):
    # Fork preserves the supplied adapter (which can be an in-process function or
    # a CLI wrapper), while isolating the processes and their transaction state.
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(len(packets)) if len(packets) > 1 else None
    children = []
    try:
        for packet in packets:
            reader, writer = context.Pipe(duplex=False)
            child = context.Process(target=_deliver, args=(solve, packet, barrier, writer))
            child.start()
            writer.close()
            children.append((child, reader))
        deadline = time.monotonic() + 20
        responses = []
        for child, reader in children:
            if not reader.poll(max(0, deadline - time.monotonic())):
                raise TimeoutError("queue process timed out")
            returned, value = reader.recv()
            if not returned:
                raise ValueError(f"queue process failed: {value}")
            responses.append(value)
        return responses
    finally:
        for child, reader in children:
            reader.close()
            child.join(timeout=0.5)
            if child.is_alive():
                child.terminate()
                child.join(timeout=1)


def _replay_enqueue(solve, db):
    _enqueue(solve, db)
    _enqueue(solve, db)
    _row(solve, db, "queued")
    _ok(solve(_packet(db, "enqueue", payload="different bytes")), False)
    _row(solve, db, "queued")
    return "matching repeat accepted; conflicting payload refused"


def _offline(solve, db):
    _ok(_independent(solve, [_packet(db, "enqueue")])[0])
    row = _ok(_independent(solve, [_packet(db, "read", now=10000)])[0])
    if row.get("status") != "queued":
        raise ValueError(f"order did not survive an offline worker: {row!r}")
    _lease(solve, db, now=10001)
    return "fresh processes recovered queued work after simulated downtime"


def _race(solve, db):
    _enqueue(solve, db)
    packets = [_packet(db, "lease", worker=worker) for worker in ("author-A", "author-B", "author-C")]
    responses = _independent(solve, packets)
    if any(not isinstance(value, dict) or type(value.get("ok")) is not bool for value in responses):
        raise ValueError(f"expected an explicit decision from each process; got {responses!r}")
    winners = [(packet, value) for packet, value in zip(packets, responses) if value["ok"]]
    if len(winners) != 1:
        raise ValueError(f"expected one winner, got {len(winners)}")
    packet, value = winners[0]
    token = value.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("winner did not receive a lease token")
    _ok(solve(_packet(db, "finish", token=token, worker=packet["worker"], now=101, payload="checked")))
    _row(solve, db, "done", "checked", now=101)
    return "three independent processes raced; one won and committed its result"


def _finish_identity(solve, db):
    _enqueue(solve, db)
    token = _lease(solve, db)
    _ok(solve(_packet(db, "finish", worker="author-B", token=token, now=101)), False)
    _ok(solve(_packet(db, "finish", token="wrong-token", now=101)), False)
    _row(solve, db, "leased", now=101)
    return "worker and lease token were both checked"


def _expiry(solve, db):
    _enqueue(solve, db)
    first = _lease(solve, db)
    _ok(solve(_packet(db, "lease", worker="author-B", now=104)), False)
    _ok(solve(_packet(db, "finish", token=first, now=105)), False)
    second = _lease(solve, db, worker="author-B", now=105)
    if second == first:
        raise ValueError("new lease reused expired token")
    _ok(solve(_packet(db, "finish", token=first, now=106)), False)
    _ok(solve(_packet(db, "finish", worker="author-B", token=second, now=106, payload="replacement")))
    _row(solve, db, "done", "replacement", now=106)
    return "expiry boundary enforced and stale writer fenced after reassignment"


def _same_worker_new_lease(solve, db):
    _enqueue(solve, db)
    old = _lease(solve, db)
    new = _lease(solve, db, now=107)
    if new == old:
        raise ValueError("reassigned lease did not get a fresh token")
    _ok(solve(_packet(db, "finish", token=old, now=108)), False)
    _ok(solve(_packet(db, "finish", token=new, now=108, payload="after recovery")))
    _row(solve, db, "done", "after recovery", now=108)
    return "a restarted worker using its old token could not finish"


def _repeat_finish(solve, db):
    _enqueue(solve, db)
    token = _lease(solve, db)
    finish = _packet(db, "finish", now=102, token=token, payload="same receipt")
    _ok(solve(finish.copy()))
    _ok(_independent(solve, [finish.copy()])[0])
    _ok(solve({**finish, "payload": "rewritten result"}), False)
    _ok(solve(_packet(db, "lease", worker="author-B", now=200)), False)
    _row(solve, db, "done", "same receipt", now=200)
    return "exact completion replay accepted; completed result remained immutable"


def _restore(solve, db):
    _enqueue(solve, db)
    token = _lease(solve, db)
    _ok(solve(_packet(db, "finish", now=101, token=token, payload="baseline")))
    _ok(solve(_packet(db, "enqueue", job="display-2", key="request-B")))
    other = db.with_name("restored.sqlite")
    if not db.is_file():
        raise ValueError("queue did not create the requested database")
    # Use SQLite's consistent backup API, including committed WAL frames.
    with sqlite3.connect(db) as source, sqlite3.connect(other) as dest:
        source.backup(dest)
    _row(solve, other, "done", "baseline", now=110)
    _row(solve, other, "queued", job="display-2", key="request-B", now=110)
    return "SQLite backup restored one completed result and one queued job"


CASES = (
    ("enqueue retry and payload conflict", _replay_enqueue),
    ("offline queue and fresh process recovery", _offline),
    ("concurrent lease claimants", _race),
    ("lease identity checks", _finish_identity),
    ("expiry and stale finisher", _expiry),
    ("same worker recovery with fresh token", _same_worker_new_lease),
    ("lost finish acknowledgement and retry", _repeat_finish),
    ("restore two persisted states", _restore),
)


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, check in CASES:
        try:
            with TemporaryDirectory(prefix="lab-queue-grade-") as folder:
                detail = check(solve, Path(folder) / "queue.sqlite")
            report.append((name, True, detail))
        except Exception as exc:
            report.append((name, False, f"{type(exc).__name__}: {exc}"[:400]))
    return report
