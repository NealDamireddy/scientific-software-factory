"""Evaluate generated scalar Python on independent inputs using the factory interpreter."""

from math import isclose

from labfactory.tabular_analysis import evaluate


def _calibration_observations():
    # The device model is signal = offset + sensitivity * known. Replacing
    # the whole standards batch distinguishes using calibration from memorizing it.
    rows = []
    for offset, sensitivity in [(13.5, 8.25), (77.0, 2.5)]:
        standards = [[offset + sensitivity * k, k] for k in (0.0, 2.0, 7.0, 18.0)]
        for known, dilution in [(0.75, 1.0), (5.4, 3.0), (15.125, 2.5)]:
            rows.append((standards, offset + sensitivity * known, dilution, known * dilution))
    return rows


def _cases():
    calibration = _calibration_observations()
    return [
        ("calibration_with_dilution", "mg/L",
         "Fit concentration against detector signal by ordinary least squares with a free intercept "
         "using this batch's standards. Report the concentration of the original sample. The signal "
         "comes from the diluted sample; factor is the fold dilution.", calibration),
        ("calibration_paraphrase", "mg/L",
         "The paired calibrants give response (signal) and assigned amount per litre (known). "
         "Regress the assigned values on the responses, allowing an intercept. Apply the resulting "
         "line to the response of the measured aliquot, then restore the undiluted basis using its "
         "fold dilution in factor.", calibration),
        ("inverse_calibration_noisy_standards", "mg/L",
         "Regress detector signal on known concentration by ordinary least squares with a fitted "
         "intercept. Invert that fitted line for the measured signal and multiply by the dilution "
         "factor. Use the current batch of standards.",
         # known = [0, 1, 2, 3]; residuals [+1, -1, -1, +1] have zero
         # covariance with known. The exact forward fit has intercept 7 and slope 4.
         [([[8, 0], [10, 1], [14, 2], [20, 3]], 13, 5, 7.5),
          ([[8, 0], [10, 1], [14, 2], [20, 3]], 17, 1.5, 3.75)]),
        ("direct_density", "g/mL",
         "Report the density of each liquid. Signal is the net mass in grams. Factor contains "
         "that aliquot's dispensed volume in millilitres. No calibration is used.",
         [([], 7.53, 6, 1.255), ([], 19.8, 18, 1.1), ([], 0.51, 0.75, 0.68)]),
        ("density_paraphrase", "g/mL",
         "For each portion compute its mass per unit volume. The tared balance reading (g) is "
         "in signal and the measured aliquot size (mL) is in factor. There are no standards.",
         [([], 13.89, 15, 0.926), ([], 0.5625, 0.5, 1.125)]),
        ("constant_blank_then_dilution", "mAU",
         "Signal is the diluted sample's measured absorbance in mAU. Subtract the independently "
         "measured blank of 0.27 mAU from the signal, then multiply the corrected absorbance by "
         "the row's dilution factor. Report original-sample absorbance in mAU.",
         [([], 2.17, 2.5, 4.75), ([], 0.42, 4, 0.6), ([], 0.27, 3, 0.0)]),
        ("blank_changed_between_protocols", "mAU",
         "Remove the offset of 1.125 mAU from each measured signal. To undo dilution, multiply "
         "the remainder by the fold dilution given in factor. Express the result in mAU.",
         [([], 2.625, 3, 4.5), ([], 5.375, 2, 8.5)]),
        ("clarify_missing_blank", "mAU",
         "Signal is measured absorbance in mAU. Remove the session blank before reporting "
         "absorbance. Factor is the fold dilution. The blank result has not been supplied.", None),
        ("clarify_missing_factor_basis", "mg/L",
         "The detector returns a signal. An operator entered a row factor. Report original "
         "concentration in mg/L. The calibration method and the meaning of factor are unspecified.", None),
        ("clarify_missing_mass_units", "g/mL",
         "For liquid density the balance reading is in signal and volume in mL is in factor. "
         "The balance export has no unit metadata and the operator cannot recall whether readings "
         "were recorded in grams or milligrams.", None),
    ]


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    results = []
    for name, unit, protocol, observations in _cases():
        try:
            reply = solve({"protocol": protocol, "fields": ["signal", "factor"], "unit": unit})
            if observations is None:
                question = reply.get("needs_input")
                passed = isinstance(question, str) and bool(question.strip()) and not reply.get("source")
                detail = "Requested clarification" if passed else "Expected a question without executable source"
            else:
                artifact = {"source": reply["source"], "tests": [], "explanation": ""}
                matched = 0
                for standards, signal, factor, expected in observations:
                    actual = evaluate(artifact, standards, signal, factor, range_gate=False)
                    if isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-9):
                        matched += 1
                passed = matched == len(observations) and not reply.get("needs_input")
                detail = f"{matched}/{len(observations)} independent numerical predictions matched"
        except Exception as exc:
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, passed, detail))
    return results
