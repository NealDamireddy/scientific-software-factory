"""Public-demo and private-lab authorization with already authenticated principals."""

from copy import deepcopy


DEMO = "public_demo"
PRIVATE = "private_lab"
LAB = "north-teaching"
OTHER = "south-teaching"

# A membership name is a fixture label. Real audit IDs differ from all labels.
PRINCIPALS = {
    "visitor": None,
    "reviewer": {"id": "H. Okafor", "role": "reviewer", "lab": LAB},
    "agent": {"id": "meter-worker-09", "role": "agent", "lab": LAB},
    "observer": {"id": "L. Singh", "role": "observer", "lab": LAB},
    "other reviewer": {"id": "K. Ray", "role": "reviewer", "lab": OTHER},
    "other agent": {"id": "batch-worker-17", "role": "agent", "lab": OTHER},
    "other observer": {"id": "E. Jones", "role": "observer", "lab": OTHER},
}

ALL = set(PRINCIPALS)
LOCAL_AGENT = {"agent"}
LOCAL_REVIEWER = {"reviewer"}
LOCAL_READERS = {"reviewer", "observer"}
ACCESS = {
    DEMO: {"read_library": ALL, "read_upload": ALL, "see_control": ALL,
           "approve": ALL, "work_context": LOCAL_AGENT, "claim": LOCAL_AGENT},
    PRIVATE: {"read_library": ALL, "read_upload": LOCAL_READERS, "see_control": LOCAL_REVIEWER,
              "approve": LOCAL_REVIEWER, "work_context": LOCAL_AGENT, "claim": LOCAL_AGENT},
}


def _trial(mode, action, label, allowed, **overrides):
    principal = PRINCIPALS[label]
    payload = {"mode": mode, "action": action, "lab": LAB, "record_lab": LAB,
               "principal": deepcopy(principal), "submission": 3, "latest": 3, "passed": True,
               **overrides}
    actor = None
    if allowed and action in {"approve", "claim"}:
        actor = "Public reviewer" if (mode, action) == (DEMO, "approve") else principal["id"]
    return payload, allowed, actor


def _cases():
    for mode, actions in ACCESS.items():
        for action, members in actions.items():
            yield f"{mode} {action}", [
                _trial(mode, action, label, label in members) for label in PRINCIPALS
            ]
        # A receiving lab never sees another lab's records, even if the principal is from that lab.
        yield f"{mode} cross-lab records", [
            _trial(mode, action, label, action == "read_library", record_lab=OTHER)
            for action in actions for label in PRINCIPALS
        ]
        yield f"{mode} approval preconditions", [
            _trial(mode, "approve", label, False, submission=number, latest=latest, passed=passed)
            for number, latest, passed in [(2, 3, True), (4, 3, True), (0, 0, True), (3, 3, False)]
            for label in ("reviewer", "agent", "visitor")
        ]
        yield f"{mode} unavailable actions", [
            _trial(mode, "unrecognized", label, False) for label in PRINCIPALS
        ]


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, cases in _cases():
        failures = []
        for payload, allowed, actor in cases:
            description = (f"{payload['action']} role={payload['principal']} record={payload['record_lab']} "
                           f"number={payload['submission']}/{payload['latest']} passed={payload['passed']}")
            try:
                actual = solve(payload)
                if (not isinstance(actual, dict) or actual.get("allow") is not allowed
                        or "actor" not in actual or actual["actor"] != actor):
                    failures.append(f"{description}: expected {(allowed, actor)!r}, got {actual!r}")
            except Exception as exc:
                failures.append(f"{description}: {type(exc).__name__}: {exc}")
        total = len(cases)
        detail = f"{total - len(failures)}/{total} decisions correct"
        if failures:
            detail += f"; first difference: {failures[0]}"
        report.append((name, not failures, detail))
    return report
