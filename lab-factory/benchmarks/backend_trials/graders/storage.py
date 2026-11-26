"""Black-box experiments on immutable binary records in a local storage root."""

import hashlib
import multiprocessing
from tempfile import TemporaryDirectory
import time


class Mismatch(Exception):
    """Short scorer diagnostic with no record contents."""


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _request(root, op, key="inventory", data=None):
    packet = {"root": str(root), "op": op, "key": key}
    if op == "put":
        packet["payload"] = data
    return packet


def _decision(response):
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        raise Mismatch("response missing a boolean decision")
    return response["ok"]


def _write(solve, root, key, data, expected=True):
    response = solve(_request(root, "put", key, data))
    if _decision(response) != expected:
        raise Mismatch(f"{key}: unexpected put decision")
    if expected and response.get("digest") != _digest(data):
        raise Mismatch(f"{key}: put digest mismatch")


def _read(solve, root, key, data):
    response = solve(_request(root, "get", key))
    if data is None:
        if _decision(response) or response.get("payload") is not None:
            raise Mismatch(f"{key}: missing record returned")
        return
    if not _decision(response) or response.get("digest") != _digest(data):
        raise Mismatch(f"{key}: get decision or digest mismatch")
    if not isinstance(response.get("payload"), bytes) or response["payload"] != data:
        raise Mismatch(f"{key}: byte round trip failed")


def _keys(solve, root, want):
    response = solve(_request(root, "list"))
    if not _decision(response) or response.get("keys") != sorted(want):
        raise Mismatch("listed keys differ from the sorted set of acknowledged records")


def _absent(solve, root):
    _keys(solve, root, [])
    _read(solve, root, "unknown-01", None)
    _keys(solve, root, [])
    return "missing lookup left empty inventory intact"


def _roundtrip(solve, root):
    for key, payload in [("middle-2", bytes(range(256))), ("early-1", b""), ("later-3", b"\r\n\x00\xff")]:
        _write(solve, root, key, payload)
        _read(solve, root, key, payload)
    _keys(solve, root, ["middle-2", "early-1", "later-3"])
    return "empty and non-text records round-tripped with exact hashes"


def _idempotence(solve, root):
    original = bytes(range(251))
    _write(solve, root, "revision-2", original)
    _write(solve, root, "revision-2", original)
    _write(solve, root, "revision-2", original + b"!", expected=False)
    _keys(solve, root, ["revision-2"])
    _read(solve, root, "revision-2", original)
    return "same content retry accepted; conflicting revision preserved original data"


def _aliases(solve, root):
    payload = bytes(range(99))
    for key in ["blue-4", "amber-3"]:
        _write(solve, root, key, payload)
    _write(solve, root, "blue-4", b"replacement", expected=False)
    _keys(solve, root, ["blue-4", "amber-3"])
    for key in ["amber-3", "blue-4"]:
        _read(solve, root, key, payload)
    return "both logical keys resolve to the independently verified original bytes"


def _child(solve, packet, barrier, writer):
    try:
        if barrier is not None:
            barrier.wait(timeout=10)
        response = solve(packet)
        # Return evidence only. A candidate can include extra fields or echo its input.
        data = response.get("payload") if isinstance(response, dict) else None
        summary = (_decision(response), response.get("digest"), _digest(data) if isinstance(data, bytes) else None)
        writer.send(("ok", summary))
    except Exception as exc:
        writer.send(("error", type(exc).__name__))
    finally:
        writer.close()


def _processes(solve, packets):
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(len(packets)) if len(packets) > 1 else None
    children = []
    try:
        for packet in packets:
            reader, writer = context.Pipe(duplex=False)
            child = context.Process(target=_child, args=(solve, packet, barrier, writer))
            child.start()
            writer.close()
            children.append((child, reader))
        responses = []
        deadline = time.monotonic() + 15
        for child, reader in children:
            if not reader.poll(max(0, deadline - time.monotonic())):
                raise Mismatch("storage process timed out")
            status, summary = reader.recv()
            if status != "ok":
                raise Mismatch(f"storage process raised {summary}")
            responses.append(summary)
        return responses
    finally:
        for child, reader in children:
            reader.close()
            child.join(timeout=0.5)
            if child.is_alive():
                child.terminate()
                child.join(timeout=1)


def _restart(solve, root):
    data = b"saved-then-reopened"
    digest = _digest(data)
    key = "generation-07"
    first, = _processes(solve, [_request(root, "put", key, data)])
    if first[:2] != (True, digest):
        raise Mismatch("first process did not persist the expected digest")
    second, = _processes(solve, [_request(root, "get", key)])
    if second != (True, digest, digest):
        raise Mismatch("independent process failed to recover the original bytes")
    _keys(solve, root, [key])
    return "fresh sibling processes wrote and recovered identical content"


def _race(solve, root):
    # Compete over an empty root to exercise initialization as well as publication.
    key = "competing-record"
    values = [b"first submission", b"other submission"]
    responses = _processes(solve, [_request(root, "put", key, data) for data in values])
    winners = [i for i, result in enumerate(responses) if result[0]]
    if len(winners) != 1:
        raise Mismatch(f"{len(winners)} successful writes to an immutable key")
    winner = winners[0]
    if responses[winner][1] != _digest(values[winner]):
        raise Mismatch("winning process returned an incorrect digest")
    _read(solve, root, key, values[winner])
    _keys(solve, root, [key])
    return "two OS processes contended; the one acknowledged payload survived"


CHUNK = 512 * 1024
CHUNKS = 24


def _block(i):
    # SHAKE's independent streams defeat compression shortcuts without large checked-in data.
    return hashlib.shake_256(f"storage-trial-record-{i}".encode("ascii")).digest(CHUNK)


def _load(solve, root):
    """Score growth separately from preserving every earlier acknowledgement after a refusal."""
    keys = [f"chunk-{i:02d}" for i in range(CHUNKS)]
    accepted, refused = [], []
    for i, key in enumerate(keys):
        data = _block(i)
        response = solve(_request(root, "put", key, data))
        if _decision(response):
            if response.get("digest") != _digest(data):
                raise Mismatch(f"{key}: invalid digest on acknowledged write")
            accepted.append(i)
        else:
            refused.append(i)
    # Capacity requires all 24 payloads to be readable, not merely acknowledged.
    capacity = len(accepted) == CHUNKS
    checked = 0
    try:
        if not accepted:
            raise Mismatch("no accepted writes to check for integrity")
        _write(solve, root, keys[accepted[0]], b"conflict", expected=False)
        for i in accepted:
            _read(solve, root, keys[i], _block(i))
            checked += 1
        for i in refused:
            _read(solve, root, keys[i], None)
        _keys(solve, root, [keys[i] for i in accepted])
        integrity, detail = True, f"{checked} accepted records intact, {len(refused)} capacity refusals"
    except Exception as exc:
        integrity, detail = False, _reason(exc)
    return [
        ("12 MiB of unique incompressible data", capacity and integrity,
         f"{len(accepted)}/{CHUNKS} half-MiB writes accepted; {checked} verified"),
        ("atomicity of refusals under cumulative load", integrity, detail),
    ]


def _reason(exc):
    return str(exc) if isinstance(exc, Mismatch) else f"candidate or adapter raised {type(exc).__name__}"


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, case in [
        ("missing record in a new root", _absent),
        ("binary data and sorted enumeration", _roundtrip),
        ("immutable key retries", _idempotence),
        ("independent keys with equal content", _aliases),
        ("restart recovery across processes", _restart),
        ("concurrent conflicting publication", _race),
    ]:
        try:
            with TemporaryDirectory(prefix="lab-storage-trial-") as root:
                detail = case(solve, root)
            report.append((name, True, detail))
        except Exception as exc:
            report.append((name, False, _reason(exc)))
    try:
        with TemporaryDirectory(prefix="lab-storage-load-") as root:
            report.extend(_load(solve, root))
    except Exception as exc:
        for name in ("12 MiB of unique incompressible data", "atomicity of refusals under cumulative load"):
            report.append((name, False, _reason(exc)))
    return report
