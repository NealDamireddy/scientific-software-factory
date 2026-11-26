"""Durable work-order and review checks on a fresh SQLite path for each case."""

from hashlib import sha256
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
import time


ARTIFACT_1 = "a = 1\n"
ARTIFACT_2 = "a = 2\n"


def _request(db, op, actor="reviewer-a", role="reviewer", **fields):
    return {"db": db, "order": "order-a", "op": op, "actor": actor, "role": role, **fields}


def _call(solve, payload, want=True):
    reply = solve(payload)
    assert isinstance(reply, dict) and reply.get("ok") is want, f"{payload['op']} expected ok={want}; got {reply!r}"
    return reply


def _state(solve, db, **expected):
    actual = _call(solve, _request(db, "read"))
    for field, value in expected.items():
        assert field in actual and actual[field] == value, f"read.{field}: expected {value!r}; got {actual.get(field)!r}"
    return actual


def _create(solve, db):
    _call(solve, _request(db, "create"))


def _agent(db, op, actor="author-a", **kw):
    return _request(db, op, actor, "agent", **kw)


def _first(solve, db):
    _create(solve, db)
    _call(solve, _agent(db, "claim"))
    _call(solve, _agent(db, "submit", artifact=ARTIFACT_1, submission=1))


def _digest(content):
    return sha256(content.encode("ascii")).hexdigest()


def _child(solve, request, gate, sender):
    try:
        sender.send("ready")
        if not gate.wait(8):
            raise TimeoutError("start barrier timed out")
        sender.send((True, solve(request)))
    except Exception as exc:
        sender.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()


def _independent(solve, requests):
    """Each fork inherits the function, including dynamically loaded candidate modules."""
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    children = []
    try:
        for request in requests:
            reader, writer = ctx.Pipe(duplex=False)
            process = ctx.Process(target=_child, args=(solve, request, start, writer))
            process.start()
            writer.close()
            children.append((reader, process))
        deadline = time.monotonic() + 12
        for reader, _ in children:
            assert reader.poll(max(0, deadline - time.monotonic())), "child timed out initializing"
            assert reader.recv() == "ready"
        start.set()
        replies = []
        for reader, _ in children:
            assert reader.poll(max(0, deadline - time.monotonic())), "child timed out executing the request"
            completed, reply = reader.recv()
            assert completed, f"child raised {reply!r}"
            replies.append(reply)
        return replies
    finally:
        start.set()
        for reader, process in children:
            reader.close()
            process.join(0.5)
            if process.is_alive():
                process.terminate()
                process.join(2)


def _creation(solve, db):
    _create(solve, db)
    _state(solve, db, status="open", owner=None, submission=0, digest=None, events=["create"])


def _racing_claims(solve, db):
    _create(solve, db)
    contenders = ("author-a", "author-b", "author-c", "author-d")
    replies = _independent(solve, [_agent(db, "claim", actor) for actor in contenders])
    assert all(isinstance(reply, dict) and isinstance(reply.get("ok"), bool) for reply in replies), repr(replies)
    winners = [actor for actor, reply in zip(contenders, replies) if reply["ok"]]
    assert len(winners) == 1, f"winning agents: {winners}"
    _state(solve, db, status="in_progress", owner=winners[0], events=["create", "claim"])


def _foreign_submission(solve, db):
    _create(solve, db)
    _call(solve, _agent(db, "claim"))
    _call(solve, _agent(db, "submit", "author-b", submission=1, artifact=ARTIFACT_1), False)
    _state(solve, db, owner="author-a", status="in_progress", submission=0, digest=None, events=["create", "claim"])


def _state_transitions(solve, db):
    _call(solve, _agent(db, "create"), False)
    _create(solve, db)
    _call(solve, _request(db, "claim"), False)
    _call(solve, _agent(db, "submit", submission=1, artifact=ARTIFACT_1), False)
    _call(solve, _request(db, "approve", submission=1), False)
    _state(solve, db, status="open", owner=None, submission=0, events=["create"])


def _reviewer_only(solve, db):
    _first(solve, db)
    for operation in ("reject", "approve"):
        _call(solve, _agent(db, operation, submission=1), False)
    _state(solve, db, status="in_review", digest=_digest(ARTIFACT_1), events=["create", "claim", "submit"])


def _released_digest(solve, db):
    _first(solve, db)
    _call(solve, _request(db, "approve", submission=1))
    _call(solve, _agent(db, "submit", submission=2, artifact=ARTIFACT_2), False)
    _state(solve, db, status="released", digest=_digest(ARTIFACT_1), submission=1,
           events=["create", "claim", "submit", "approve"])


def _rejection_and_stale(solve, db):
    _first(solve, db)
    _call(solve, _request(db, "reject", submission=1))
    _state(solve, db, status="open", owner=None)
    _call(solve, _agent(db, "claim", "author-b"))
    _call(solve, _agent(db, "submit", "author-b", submission=2, artifact=ARTIFACT_2))
    _call(solve, _request(db, "approve", submission=1), False)
    _call(solve, _request(db, "reject", submission=1), False)
    _state(solve, db, status="in_review", submission=2, digest=_digest(ARTIFACT_2),
           events=["create", "claim", "submit", "reject", "claim", "submit"])
    _call(solve, _request(db, "approve", submission=2))
    _state(solve, db, status="released", submission=2, digest=_digest(ARTIFACT_2))


def _duplicates(solve, db):
    _create(solve, db)
    for payload in (_agent(db, "claim"), _agent(db, "submit", submission=1, artifact=ARTIFACT_1),
                    _request(db, "approve", submission=1)):
        _call(solve, payload)
        repeat = solve(payload.copy())
        assert isinstance(repeat, dict) and isinstance(repeat.get("ok"), bool), f"malformed retry reply: {repeat!r}"
    _state(solve, db, status="released", submission=1, digest=_digest(ARTIFACT_1),
           events=["create", "claim", "submit", "approve"])


def _restart(solve, db):
    # All writes originate in separate child processes; only the SQLite file can bridge them.
    steps = [_request(db, "create"), _agent(db, "claim"),
             _agent(db, "submit", submission=1, artifact=ARTIFACT_1),
             _request(db, "approve", submission=1)]
    for step in steps:
        reply, = _independent(solve, [step])
        assert reply.get("ok") is True, f"{step['op']} after restart: {reply!r}"
    _state(solve, db, status="released", digest=_digest(ARTIFACT_1), submission=1,
           events=["create", "claim", "submit", "approve"])


def _isolation(solve, db):
    _first(solve, db)
    other = "order-b"
    _call(solve, _request(db, "create", order=other))
    _call(solve, _request(db, "approve", submission=1, order=other), False)
    _state(solve, db, status="in_review", submission=1, events=["create", "claim", "submit"])
    read = _call(solve, _request(db, "read", order=other))
    assert read["status"] == "open" and read["events"] == ["create"], repr(read)


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, test in [
        ("persistent creation state", _creation), ("four concurrent claimants", _racing_claims),
        ("role and lifecycle preconditions", _state_transitions),
        ("claim owner governs submission", _foreign_submission), ("agent cannot decide", _reviewer_only),
        ("released digest immutable", _released_digest), ("rejection and stale decisions", _rejection_and_stale),
        ("duplicate retries have one event", _duplicates), ("restart between every operation", _restart),
        ("work orders isolated", _isolation),
    ]:
        try:
            with TemporaryDirectory(prefix="lab-review-trial-") as directory:
                test(solve, str(Path(directory) / "reviews.sqlite"))
            report.append((name, True, "observed expected state and events"))
        except Exception as exc:
            report.append((name, False, f"{type(exc).__name__}: {exc}"))
    return report
