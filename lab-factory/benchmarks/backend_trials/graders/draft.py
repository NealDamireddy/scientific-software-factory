"""Grade cited drafts against independent references for two simulated display models."""

from copy import deepcopy
import math


OPTIC = "Atlas-17"
THERMO = "Thermo-4"


def _doc(family, edition, kind, model, text):
    return {"id": f"{family}@{edition}", "revision": edition, "kind": kind, "model": model, "text": text}


def _sop(family, text, model=OPTIC, edition=1):
    return _doc(family, edition, "sop", model, text)


def _manual(family, text, model=OPTIC, edition=1):
    return _doc(family, edition, "manual", model, text)


def _steps(*items):
    return [(item, None, None) if isinstance(item, str) else item for item in items]


def _packet(goal, docs, model=OPTIC, as_of=3):
    return {"goal": goal, "model": model, "as_of": as_of, "documents": docs}


def _cases():
    guide = _manual("atlas-guide", "The display supports zero, set wavelength, and read display. "
                    "The wavelength range is 400 to 700 nm, inclusive.")
    blue_goal = "Read the blue optical reference."
    blue = _sop("blue-sop", "Blue optical reference procedure. First zero the display. "
                "Select a wavelength of 472.25 nm. Finally read the display.")
    blue_steps = _steps("zero", ("set_wavelength", 472.25, "nm"), "read_display")
    yield "prose instructions with a precise setting", _packet(blue_goal, [blue, guide]), blue_steps, (blue, guide)

    amber = _sop("amber-sop", "For an amber reference check, tune the wavelength to 589 nm, "
                 "then record the display reading.")
    amber_steps = _steps(("set_wavelength", 589, "nm"), "read_display")
    yield "purpose selects one of two valid procedures", _packet(
        "Check the amber reference.", [blue, amber, guide],
    ), amber_steps, (amber, guide)

    # A shared SOP may supply the method when the selected model has its own enabling manual.
    common = _sop("dark-sop", "To check a dark reference, reset the display to zero, then "
                  "record the display reading.", model="*")
    yield "shared SOP and model-specific capabilities", _packet(
        "Check the dark reference.", [guide, common],
    ), _steps("zero", "read_display"), (common, guide)

    therm = _manual("thermo-guide", "The thermometer allows the operator to set a display target "
                    "temperature from -10 C to 85 C and to read the display.", THERMO)
    warm = _sop("warm-sop", "For the warm reference check, set the target temperature to 36.75 C. "
                "Read the display after setting the target.", THERMO)
    yield "temperature method on another instrument", _packet(
        "Perform a warm reference check.", [guide, blue, warm, therm], THERMO,
    ), _steps(("set_temperature", 36.75, "C"), "read_display"), (warm, therm)

    replacement = _sop("blue-sop", "Blue optical reference procedure. Set the wavelength to "
                       "486.1 nm, then read the display.", edition=2)
    future = _sop("blue-sop", "Blue optical reference procedure. Set the wavelength to "
                  "493 nm, then read the display.", edition=4)
    yield "superseded and future SOPs excluded", _packet(
        blue_goal, [future, guide, blue, replacement], as_of=2,
    ), _steps(("set_wavelength", 486.1, "nm"), "read_display"), (replacement, guide)
    yield "historical snapshot recovers earlier SOP", _packet(
        blue_goal, [future, replacement, guide, blue], as_of=1,
    ), blue_steps, (blue, guide)

    broader = _manual("universal-guide", "This display family supports zero, setting wavelengths "
                      "from 300 to 900 nm and reading the display.", model="*")
    yield "exact manual supports the cited steps", _packet(
        blue_goal, [broader, blue, guide],
    ), blue_steps, (blue, guide)

    # Negative fixtures all need an empty draft: partial steps could appear verified.
    foreign = _manual("other-guide", guide["text"], model="Other-17")
    numeric = _sop("blue-sop", "For the blue optical reference, select 720 nm and read the display.")
    narrower = _manual("atlas-guide", "The display supports zero, setting wavelengths from 500 "
                       "to 650 nm, and reading the display.", edition=2)
    no_zero = _manual("atlas-guide", "The display supports setting wavelengths from 400 to "
                      "700 nm and reading the display. Zeroing is unavailable.")
    different = _sop("independent-blue-sop", "Blue optical reference procedure. First zero the "
                     "display, then set 598 nm and read the display.")
    no_target = _sop("blue-sop", "To read the blue optical reference, select the target "
                     "wavelength and read the display.")
    for label, packet in (
        ("manual for a different model", _packet(blue_goal, [blue, foreign])),
        ("current manual rules out the older permissible range", _packet(
            blue_goal, [blue, guide, narrower, broader])),
        ("out-of-range SOP setting", _packet(blue_goal, [guide, numeric])),
        ("explicitly unsupported requested command", _packet(blue_goal, [blue, no_zero])),
        ("conflicting independent SOPs for the same goal", _packet(blue_goal, [different, guide, blue])),
        ("ambiguous goal with competing procedures", _packet(
            "Do the reference check.", [amber, blue, guide])),
        ("method unrelated to the requested goal", _packet("Check the amber reference.", [blue, guide])),
        ("no numerical target in the procedure", _packet(blue_goal, [no_target, guide])),
        ("manual alone cannot supply a method", _packet(blue_goal, [guide])),
    ):
        yield label, packet, [], ()


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, packet, expected, evidence in _cases():
        try:
            answer = solve(deepcopy(packet))
            status = "draft" if expected else "needs_input"
            if not isinstance(answer, dict) or answer.get("status") != status:
                raise ValueError(f"expected {status}; got {answer!r}")
            steps = answer.get("steps")
            if not isinstance(steps, list) or len(steps) != len(expected):
                raise ValueError(f"expected {len(expected)} steps; got {steps!r}")
            doc_ids = sorted(doc["id"] for doc in evidence)
            for index, (row, (command, val, unit)) in enumerate(zip(steps, expected), start=1):
                if row["command"] != command or row["unit"] != unit:
                    raise ValueError(f"step {index} must be {command} in {unit!r}")
                value = row["value"]
                if val is None:
                    if value is not None:
                        raise ValueError(f"step {index} needs a null value")
                elif type(value) not in (int, float) or not math.isclose(value, val, rel_tol=0, abs_tol=1e-10):
                    raise ValueError(f"step {index} expected {val}, got {value!r}")
                if sorted(row["citations"]) != doc_ids:
                    raise ValueError(f"step {index} must cite {doc_ids!r}")
            report.append((name, True, f"{status}, {len(steps)} step(s)"))
        except Exception as exc:
            report.append((name, False, f"{type(exc).__name__}: {exc}"[:400]))
    return report
