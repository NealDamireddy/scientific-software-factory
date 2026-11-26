"""Offline authorization and audit policy for host-verified principal fixtures."""


def _record_in_lab(request):
    lab = request.get("lab")
    if type(lab) is not int and not (isinstance(lab, str) and lab.strip()):
        return False
    record_lab = request.get("record_lab")
    return type(record_lab) is type(lab) and record_lab == lab


def _member_with_role(*roles):
    def matches(request):
        principal = request.get("principal")
        if not isinstance(principal, dict):
            return False
        identity = principal.get("id")
        return (
            isinstance(identity, str)
            and bool(identity.strip())
            and type(principal.get("lab")) is type(request["lab"])
            and principal.get("lab") == request["lab"]
            and principal.get("role") in roles
        )

    return matches


def _current_and_passing(request):
    submission = request.get("submission")
    latest = request.get("latest")
    return (
        type(submission) is int
        and submission > 0
        and type(latest) is int
        and submission == latest
        and request.get("passed") is True
    )


_agent = _member_with_role("agent")
_reviewer = _member_with_role("reviewer")
_reader = _member_with_role("observer", "reviewer")

# A listed action requires every predicate in its row. An empty row is public.
_COMMON = {
    "read_library": (),
    "work_context": (_record_in_lab, _agent),
    "claim": (_record_in_lab, _agent),
}
_POLICIES = {
    "public_demo": {
        **_COMMON,
        "read_upload": (_record_in_lab,),
        "see_control": (_record_in_lab,),
        "approve": (_record_in_lab, _current_and_passing),
    },
    "private_lab": {
        **_COMMON,
        "read_upload": (_record_in_lab, _reader),
        "see_control": (_record_in_lab, _reviewer),
        "approve": (_record_in_lab, _reviewer, _current_and_passing),
    },
}


def _audit_actor(request, allowed):
    if not allowed or request["action"] not in ("approve", "claim"):
        return None
    if request["action"] == "approve" and request["mode"] == "public_demo":
        return "Public reviewer"
    return request["principal"]["id"]


def solve(request):
    """Return an access decision and the audit identity for an allowed write."""
    if not isinstance(request, dict):
        return {"allow": False, "actor": None}
    mode = request.get("mode")
    action = request.get("action")
    rules = None
    if isinstance(mode, str) and isinstance(action, str):
        rules = _POLICIES.get(mode, {}).get(action)
    allowed = rules is not None and all(check(request) for check in rules)
    return {"allow": allowed, "actor": _audit_actor(request, allowed)}
