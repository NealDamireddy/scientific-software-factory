# WO-15 implementation plan

## Summary

Reject candidates that return valid results for a nonfinite frozen calibration or silently refit supplied standards. Exercise the actual release publisher, then repeat the same submissions after changing its mandatory checks.

## Code reuse and package structure

Use the independent power-of-two count fixtures and frozen-fit oracle in factory/scientific_contract.py. Reuse the historical manifest loader, publication transaction, isolation probe, candidate signing helper, structured withholding and result identity functions. Keep dedicated tests for runtime projection and signed publication in tests/. Retain the base reports in this directory.

## Components and flow

Approved preparation supplies a signed candidate to verify_release. The mandatory suite runs raw challenges inside the offline sandbox and compares each response with the independently calculated expected envelope. Withhold every estimate and SD for a bad fit, preserving calibration ID, sample order and actual timestamps. The normal analyze_release entry point rejects nonempty time-course standards and withholds invalid fits, including when replaying an older release. A conflicting set of valid standards independently exercises generated source at publication. Keep the candidate input/output protocol and historical specifications readable. Version the verifier suite and check time-course certification when selecting compatible software. Keep the concentration contract stable.

## Steps

1. Record base and upstream behavior. Existing WO-8 spec approval requires empty time-course standards and WO-10 validates standard-derived frozen fits. The baseline signed mutants still pass the 49 publication checks.
2. Add twelve independent negative challenges, varying one field and one nonfinite value at a time. Add a valid competing standard set and keep frozen expectations. Cover zero/negative slope, equality/reversal of bounds, endpoints and group-local range failure.
3. Enforce the data boundary, update published verification revision and time-course reuse check. Confirm historical records stay accessible.
4. Review raw checks, runtime behavior, result identity and isolated publication evidence. Deliver one draft PR to the integration owner.

## Testing

Run dedicated frozen-calibration and signed-publication tests, existing scientific-release and measurement-mutant regressions, specification/planner/scheduler composition, B12 tests, replay and benchmark. Run Python compile checks and git diff --check. Run with macOS Seatbelt, retaining initial sandbox denial as a failed attempt. Independent aggregate reruns belong to the WO-15–19 integration owner. WO-14 model-connected rehearsal is deferred.
