# WO-16 implementation plan

## Summary

Use the existing locked, atomically replaced task record to journal each direct and prepared acquisition. Preserve the existing successful acquisition and measurement formats for replay and export. Store private simulator inputs separately.

## Code reuse and placement

Lab.collect and Lab.rerun own orchestration. A dedicated factory/b12_attempts.py helper appends and updates task acquisition_attempts independently of the existing build attempts counter. factory/followup.py keeps the released-source, approval, preparation, range and frozen calibration checks. Dedicated tests use the content-verified B12 package and the production task API. Baseline evidence is in baseline.txt.

## Flow and caller contract

WO-19 persists task.sample_id (legacy default U-01) before calling collect(task_id). collect returns the original raw/calibration/input/finding shape and raises on rejected direct inputs. WO-19 validates the direct candidate against this request. At integration, its analyze_direct caller invokes record_direct_analysis after saving the verified result, or on actual analysis failure; the hook updates the matching acquisition attempt. WO-16 retains the direct raw/calibration before returning control. Both fresh and reused follow-ups call rerun(task_id); preparation supplies the child identity and actual parent linkage. Persist the attempt before acquisition, record raw data before detector assessment, then save outcome and measurement together. The task GET response carries current and prior attempts, and only the successful measurement can enable reveal. A repeated request reuses the latest attempt, including interrupted acquisitions. Permit explicit, idempotent retry by reference to a rejected attempt. The build retry counter remains separate. A preexisting successful acquisition or measurement remains retrievable.

## Steps

1. Record pinned-base reproduction for all three failures and renamed direct samples. Capture the context and branch before source edits.
2. Implement attempt persistence, recovery and identity in the owned Lab methods. Preserve release bytes and calibration.
3. Checkpoint trusted acquisition stages around detector and candidate calls. Retain the offending raw records, preparation, timing, settings and structured failure.
4. Verify with isolated fixture failures, independent code review and supported execution of sandboxed candidates. Open an independently tested draft PR. Coordinate request dispatch and the combined case through the integration owner.

## Verification

Run dedicated unit and task API tests for saturation, incompatible blank, candidate failure, valid triplicate, legacy sample, preparation gating, restart, explicit retry, retained historical data and archived export/reveal gates. Run existing followup, lab, optics and replay tests, compile changed Python, run diff checks and lane CI. The combination of real WO-19 reuse and WO-17 archive-only refusal requires the combined reviewed head. The integration owner runs all five lanes' wider CI matrix there.
