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

## Lead verification

- `python3 -m unittest discover -s tests -v` passed all 148 tests on macOS with working Seatbelt and loopback (78.487 seconds).
- `python3 -m compileall -q factory/b12_attempts.py factory/followup.py factory/lab.py tests/test_b12_attempts.py` and `git diff --check` passed.
- GitHub draft PR #17 contains the caller/field contract and the aggregate test handoff. Its checks are reported against the exact PR head. Combined verification remains outstanding.

## Round 3 — CHANGES_REQUESTED

External review of b970864 found a preexisting loss of calibration evidence. A standard triplicate was acquired and assessed inside fit_calibration before Lab.collect had a chance to save its raw counts. Saturation and an invalid blank produced a rejected attempt with no recoverable standard readings. PR #17 had also been taken out of draft. Combined direct-analysis wiring, HTTP retry and WO-17 evidence validation remained open. The reviewer requested additional coverage for invalid candidate output and restart after the raw checkpoint. Three detector fault regressions reproduced the defect on an isolated export of the reviewed head; calibration-baseline.txt preserves their failures.

## Round 4 — APPROVED for the WO-16 repair

The instrumentation change was coordinated with the integration owner and WO-19. Only fit_calibration changes in factory/optics.py. Its optional checkpoint saves each complete standard triplicate on the current acquisition attempt before absorbance or fitting. A failed fit retains all earlier and failing standards and has no frozen calibration ID. No vial measurement, estimate or score is created. A valid fit with the same observations has identical contents and SHA-256 digest with and without the callback.

A production-code agent implemented the three call sites; the test author independently reviewed them and the lead inspected the resulting patch. The test author exercised a fresh HTTP request through normal dispatch with a known verified worker-response fixture and confirmed the same rejected attempt after reopen. Nine new tests cover first-standard saturation and bad blank, third-standard failure, callback ordering and digest parity, malformed/nonfinite candidate output, and restart after vial readings were saved. Candidate failure tests executed real isolated programs. The independent reviewer ran all 40 affected tests with real loopback and macOS Seatbelt. A separate lead probe saved nine dark, blank and sample count triples from three standards and confirmed the same values and instrument count after reopening; see calibration-restart.txt. Compilation and whitespace checks passed.

The integration auditor confirmed WO-19 at 6a6b9f737781b33382fa96bb2db0b3890ca7a11b forwards the HTTP retry key but its direct-analysis caller awaits the combined-tree callbacks. WO-17 at 7dae053cf1015456230a02f783c66c9f3b3b9c3e validates archive attempts. The runnable check_combined.py exercises actual fresh/reused dispatch, candidate success/failure, approved renamed 4× preparation, saturation/restart, explicit HTTP retry and archive-only refusal. It requires those implementations in one checkout. On this branch it compiles and exits 1 naming the missing dependencies. There is no aggregate acceptance result. Run it on an authorized combined head, record the SHA and repeat on any head or base change. Independent lane CI and the final commit are recorded in PR #17. The PR was restored to draft; no merge or work-order status change was made.

The linked blueprint's tracked suggestion 83de39f2-b375-4649-a54f-899a876c47bf documents attempt history, partial calibration, lifecycle and retry semantics. 8090 accepted it for review; approval is pending.
