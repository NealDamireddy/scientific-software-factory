"""Offline access trial. A grant maps (action, lab) to its audit actor."""


def _has_name(value):
    return isinstance(value, str) and bool(value.strip())


def _capabilities(mode, requested_lab, principal):
    grants = {("read_library", None): None}
    if mode not in ("public_demo", "private_lab"):
        return grants

    if mode == "public_demo" and _has_name(requested_lab):
        grants[("read_upload", requested_lab)] = None
        grants[("see_control", requested_lab)] = None
        grants[("approve", requested_lab)] = "Public reviewer"

    if not isinstance(principal, dict):
        return grants
    lab = principal.get("lab")
    actor = principal.get("id")
    if not (_has_name(lab) and _has_name(actor)):
        return grants

    role = principal.get("role")
    if role == "agent":
        grants[("work_context", lab)] = None
        grants[("claim", lab)] = actor
    elif mode == "private_lab" and role in ("reviewer", "observer"):
        grants[("read_upload", lab)] = None
        if role == "reviewer":
            grants[("see_control", lab)] = None
            grants[("approve", lab)] = actor
    return grants


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

    action = request.get("action")
    if not isinstance(action, str):
        return denied
    lab = request.get("lab")
    scope = None
    if action != "read_library":
        if not _has_name(lab) or lab != request.get("record_lab"):
            return denied
        scope = lab

    grants = _capabilities(request.get("mode"), lab, request.get("principal"))
    key = (action, scope)
    if key not in grants or (action == "approve" and not _can_approve(request)):
        return denied
    return {"allow": True, "actor": grants[key]}
