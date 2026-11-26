"""Black-box planning checks using an in-memory optical and thermometer display."""

from copy import deepcopy
import math


def _step(command, value=None, unit=None):
    return {"command": command, "value": value, "unit": unit}


def _packet(steps, *, released=True, online=True, meter_unit="nm", temperature="K"):
    limits = (400, 700) if meter_unit == "nm" else (0.4, 0.7)
    bounds = (273.15, 310.15) if temperature == "K" else (0, 37)
    return {
        "goal": "Display the reference reading per the supplied SOP.",
        "manual": {
            "id": "display-guide@7",
            "commands": {
                "select_reference": {"unit": meter_unit, "min": limits[0], "max": limits[1]},
                "display_temperature": {"unit": temperature, "min": bounds[0], "max": bounds[1]},
                "read_display": {"unit": None, "min": None, "max": None},
            },
        },
        "sop": {"id": "optical-reference@3", "steps": steps},
        "released": released,
        "online": online,
    }


def _cases():
    read = _step("read_display")
    requested = [_step("select_reference", 0.5500004, "um"), read]
    expected = [_step("select_reference", 550.0004, "nm"), read]
    yield "unreleased stays draft", _packet(requested, released=False), "draft", expected
    yield "offline stays draft", _packet(requested, online=False), "draft", expected
    yield "released simulation preserves precision and order", _packet(requested), "simulated", expected
    yield "document IDs follow the pinned inputs", {
        **_packet([read]), "sop": {"id": "sop-revised@8", "steps": [read]},
        "manual": {**_packet([read])["manual"], "id": "display-revised@12"},
    }, "simulated", [read]
    endpoints = [_step("select_reference", 400, "nm"), _step("select_reference", 700, "nm")]
    yield "inclusive bounds in reverse optical conversion", _packet(endpoints, meter_unit="um"), "simulated", [
        _step("select_reference", 0.4, "um"), _step("select_reference", 0.7, "um"),
    ]
    yield "Celsius to kelvin at upper bound", _packet([_step("display_temperature", 37, "C")]), "simulated", [
        _step("display_temperature", 310.15, "K"),
    ]
    yield "kelvin to Celsius at lower bound", _packet(
        [_step("display_temperature", 273.15, "K")], temperature="C",
    ), "simulated", [_step("display_temperature", 0, "C")]
    invalid = {
        "unknown command after valid step": _step("nonexistent"),
        "just above range after conversion": _step("select_reference", 0.7000001, "um"),
        "incompatible physical units": _step("select_reference", 500, "K"),
        "unsupported unit": _step("select_reference", 550, "ticks"),
        "missing value": _step("select_reference", None, "nm"),
        "value on parameterless read": _step("read_display", 1, "nm"),
        "nonfinite value": _step("select_reference", float("nan"), "nm"),
    }
    for name, step in invalid.items():
        yield name, _packet([read, step]), "needs_input", []
    yield "unreleased plan still validates every step", _packet(
        [_step("select_reference", 399, "nm")], released=False,
    ), "needs_input", []


def grade(candidate):
    """Return independent case results. Report failures without interrupting other cases."""
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, packet, status, expected in _cases():
        try:
            result = solve(deepcopy(packet))
            if not isinstance(result, dict) or result.get("status") != status:
                raise ValueError(f"expected status {status}; got {result!r}")
            steps = result.get("steps")
            if not isinstance(steps, list) or len(steps) != len(expected):
                raise ValueError(f"expected {len(expected)} steps; got {steps!r}")
            for index, (got, wanted) in enumerate(zip(steps, expected), start=1):
                if got["command"] != wanted["command"] or got["unit"] != wanted["unit"]:
                    raise ValueError(f"step {index} command or unit differs")
                value = got["value"]
                if wanted["value"] is None:
                    if value is not None:
                        raise ValueError(f"step {index} takes no value")
                elif (type(value) not in (float, int) or
                      not math.isclose(value, wanted["value"], rel_tol=0, abs_tol=1e-10)):
                    raise ValueError(f"step {index} expected {wanted['value']}, got {value!r}")
                ids = [packet["sop"]["id"], packet["manual"]["id"]]
                if sorted(got["citations"]) != sorted(ids):
                    raise ValueError(f"step {index} needs both pinned references")
            report.append((name, True, f"{status}, {len(steps)} checked step(s)"))
        except Exception as exc:
            report.append((name, False, f"{type(exc).__name__}: {exc}"[:400]))
    return report
