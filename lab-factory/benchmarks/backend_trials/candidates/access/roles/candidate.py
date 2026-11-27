"""Offline access policy for host-verified principal records."""

_AGENT = frozenset({"work_context", "claim"})
_REVIEWER = frozenset({"read_upload", "see_control", "approve"})

# The None row grants permissions to every caller, including anonymous callers.
_PERMISSIONS = {
    "public_demo": {None: _REVIEWER, "agent": _AGENT},
    "private_lab": {
        "reviewer": _REVIEWER,
        "observer": frozenset({"read_upload"}),
        "agent": _AGENT,
    },
}


def _has_text(value):
    return isinstance(value, str) and bool(value.strip())


def _can_approve(request):
    submission = request.get("submission")
    latest = request.get("latest")
    return (
        type(submission) is int
        and submission > 0
        and type(latest) is int
        and submission == latest
        and request.get("passed") is True
    )


def solve(request):
    denied = {"allow": False, "actor": None}
    if not isinstance(request, dict):
        return denied
    mode = request.get("mode")
    action = request.get("action")
    if not isinstance(mode, str) or mode not in _PERMISSIONS or not isinstance(action, str):
        return denied
    if action == "read_library":
        return {"allow": True, "actor": None}

    lab = request.get("lab")
    if not _has_text(lab) or request.get("record_lab") != lab:
        return denied

    grants = _PERMISSIONS[mode]
    actor = None
    if action in grants.get(None, ()):
        if action == "approve":
            actor = "Public reviewer"
    else:
        principal = request.get("principal")
        if not isinstance(principal, dict) or principal.get("lab") != lab:
            return denied
        role = principal.get("role")
        if not _has_text(principal.get("id")) or not _has_text(role):
            return denied
        if action not in grants.get(role, ()):
            return denied
        if action in {"approve", "claim"}:
            actor = principal["id"]

    if action == "approve" and not _can_approve(request):
        return denied
    return {"allow": True, "actor": actor}
