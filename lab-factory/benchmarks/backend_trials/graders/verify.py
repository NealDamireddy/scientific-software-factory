"""Decision fixtures with independent numerical expectations and explicit domain rules."""

from math import isclose


def _case(name, program, controls, sample, properties, expected, domain=(0, 10)):
    payload = {
        "program": program,
        "controls": [
            {"x": x, "f": f, "expected": target, "tolerance": tolerance}
            for x, f, target, tolerance in controls
        ],
        "sample": {"x": sample[0], "f": sample[1]},
        "domain": list(domain),
        "properties": properties,
    }
    return name, payload, expected


def _cases():
    linear = [(0, 1, 1, 0), (5, 2, 22, 0), (10, 0.5, 10.5, 0)]
    shape = ["nondecreasing", "nonnegative"]
    return [
        _case("correct_multiple_controls", "(2*x+1)*f", linear, (6, 3), shape, 39),
        _case("inclusive_domain_boundary", "(2*x+1)*f", linear, (10, 1.5), shape, 31.5),
        _case("inclusive_absolute_tolerance", "x*f", [(1, 1, 1.125, 0.125)],
              (2, 3), [], 6),
        _case("midpoint_only_impostor", "11*f", [linear[1], linear[0], linear[2]],
              (6, 3), shape, None),
        _case("last_control_just_outside_tolerance", "x*f",
              [(0, 2, 0, 0), (4, 1, 4, 0), (8, 1, 8.126, 0.125)], (6, 2), [], None),
        _case("hold_out_of_domain_sample", "(2*x+1)*f", linear, (10.0001, 1), shape, None),
        _case("hold_out_of_domain_control", "x*f", [(11, 1, 11, 0)], (2, 1), [], None),
        _case("numerical_pole_at_sample", "f/(x-3)", [(4, 2, 2, 0)], (3, 2), [], None),
        _case("overflow_at_sample", "1e308*x", [(0, 1, 0, 0)], (4, 1), [], None),
        _case("decreasing_without_shape_constraint", "20-x", [(2, 1, 18, 0), (10, 1, 10, 0)],
              (7.5, 1), [], 12.5),
        _case("negative_is_valid_without_property", "x-8", [(1, 1, -7, 0), (9, 1, 1, 0)],
              (1.5, 1), ["nondecreasing"], -6.5),
        _case("nonnegative_constraint_between_controls", "(x-3)*(x-7)",
              [(0, 1, 21, 0), (10, 1, 21, 0)], (8, 1), ["nonnegative"], None),
        _case("nondecreasing_constraint_between_controls", "(x-5)*(x-5)+x",
              [(0, 1, 25, 0), (10, 1, 35, 0)], (9, 1), ["nondecreasing"], None),
        _case("valid_curved_response", "(x*x+1)*f",
              [(0, 1.5, 1.5, 0), (3, 2, 20, 0), (8, 0.25, 16.25, 0)],
              (4, 2.5), shape, 42.5),
        _case("no_independent_controls", "x*f", [], (6, 3), [], None),
        # The roots enclose a narrow negative interval between ordinary calibration levels.
        _case("narrow_negative_between_levels", "(x-4.12341)*(x-4.12349)",
              [(0, 1, 4.12341*4.12349, 1e-10), (10, 1, (10-4.12341)*(10-4.12349), 1e-10)],
              (7, 1), ["nonnegative"], None),
        _case("nearby_strictly_positive_curve", "(x-4.12345)*(x-4.12345)+0.00000001",
              [(0, 1, 4.12345**2+1e-8, 1e-10), (10, 1, (10-4.12345)**2+1e-8, 1e-10)],
              (7, 1), ["nonnegative"], (7-4.12345)**2+1e-8),
    ]


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    results = []
    for name, payload, expected in _cases():
        try:
            reply = solve(payload)
            value = reply["value"]
            if expected is None:
                passed = reply.get("decision") == "withhold" and value is None
                detail = f"Expected withhold and no result; received {reply!r}"
            else:
                passed = (
                    reply.get("decision") == "release" and type(value) in (float, int)
                    and isclose(value, expected, rel_tol=1e-9, abs_tol=1e-10)
                )
                detail = f"Expected release with {expected:g}; received {reply!r}"
        except Exception as exc:
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, passed, detail))
    return results
