# WO-16 independent review

## Round 1 — CHANGES_REQUESTED

An independent reviewer exercised 24 tests with the real loopback API and macOS Seatbelt runner. After a failed attempt A, a rejected retry B and a successful retry C, repeating the first retry key could return C's result. The reviewer also found that a source digest mismatch was filed under preparation. Both findings were blocking.

## Round 2 — APPROVED

The reviewer inspected factory/b12_attempts.py, factory/lab.py, factory/followup.py and tests/test_b12_attempts.py again. A repeated retry key selects its own successor and excludes any later result or score. The live task still identifies the latest attempt. Digest errors now retain the preflight stage and exact reason. A three-attempt regression and a tampered-source regression exercise both fixes. The reviewer independently ran `python3 -m unittest -q tests.test_b12_attempts tests.test_followup tests.test_lab && git diff --check` with real loopback and Seatbelt. All 25 tests passed. Zero open branch-local blockers.

## Checks and evidence

| Acceptance | Evidence |
| --- | --- |
| AC-B12-003.1 | Missing approval, preparation or verification prevents acquisition. A source digest mismatch is retained and produces zero reads. See test_prerequisites_and_verified_source_checked_before_reading. |
| AC-B12-003.2 | The task API and task.json retain saturation, bad counts, incompatible blank settings, candidate failure, volume/unit/lineage errors and the failure reason. Reopening and retrying a rejected request returns its ID and counts. Reveal/export stay gated. See tests/test_b12_attempts.py and retained-attempts.txt. |
| AC-B12-003.3 | A verified prepared release takes three new readings and pins the original calibration. The real offline runner produces the corrected estimate; replay matches, reveal succeeds only after persistence. Explicit retries preserve all earlier attempts. |
| AC-B12-003.4 | Successful export includes instrument settings and raw counts, original fit, preparation, release, dependencies, numerical checks and scientific review. Rejected attempts remain visible via the task API. The existing evidence export refuses incomplete runs. WO-17 validates forged completed archives on the combined tree. |

The baseline explorer reproduced the three lost-reading cases and renamed sample defect on a clean export of the pinned base. baseline.txt records the outcomes. The test author created the dedicated verified-fixture suite and exercised the HTTP and sandbox boundaries. The lead implemented acquisition persistence, independently reviewed and ran the tests, fixed the retry-chain and preflight issues and exercised the HTTP handler separately. retained-attempts.txt captures this exploratory probe with sampled counts and original calibration IDs. The independent reviewer owned both review rounds.

Initial restricted local execution could not start nested Seatbelt or bind loopback (23 tests, four failures and eight errors). The subsequent supported runs used both capabilities. The prior full run passed 147 tests before the final regression was added. The final-head CI checks, reviewed commit and combined-test handoff are tracked in the draft PR.
