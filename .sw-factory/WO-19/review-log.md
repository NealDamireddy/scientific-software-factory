<!--lint disable strong-marker-->

# Review Log: WO-19

**Work Order:** WO-19 — Reuse verified B12 releases for supported input changes
**Initialized At (UTC):** 2026-11-14T21:07:02Z

This file records review and verification rounds. Append new rounds; do not overwrite prior rounds.

---

## Round 1 — CHANGES_REQUESTED

The independent reviewer reproduced two blockers. A verified direct task from a foreign project could approve a child using a compatible prepared release. An unavailable execution for the parent's 2×/4× cases could also masquerade as proof that the parent safely declined prepared input. Selection and planner tests passed 16/16 despite these failures.

The revision ties approval and child dispatch to the live parent's original release, checks worker and verifier provenance, reconstructs the input and finding from raw records, and checks the frozen calibration digest. Parent verification now requires the direct release to return its own vial and calibration IDs with a review verdict and withheld estimate for both preparations. New regression tests cover both defects. Historical retained acquisitions can omit the redundant finding copy when the raw data reproduce the recorded finding. The initial restricted test run that exposed this historical shape is retained in focused-initial.log.

## Acceptance evidence

| Criterion | Branch evidence |
| --- | --- |
| AC-B12-002.2 | The presenter API checks measured above-range evidence, binds origin, sample, frozen calibration and readings to an explicit factor, and deduplicates on origin/factor. The queued child accepts preparation independently of development. See test_http_renamed_sample_and_independent_preparations_reuse_original_releases and the existing approval/retry regression. |
| AC-B12-002.3 | The verifier's 2× and 4× cases exercise a nonzero intercept and lineage. Both preparations ran through HTTP rerun and sandboxed analysis with the requested parent/child IDs, actual volumes and both concentrations in evidence. Parent sandbox errors and unsafe outputs fail release selection. |
| AC-B12-002.4 and AC-APP-003.1/.2 | The same HTTP test imports explicitly seeded verified originals, asserts zero calls to invoke_worker, distinct task IDs, exact original bytes, revision, worker and checks for direct plus both children. Fresh-then-reused test confirms both dispatch the same collect(task_id). |
| AC-APP-003.3 | Missing preparation capability dispatches one failed candidate build. Original task and source bytes remain identical. |
| AC-APP-003.4 | The selection suite rejects changed units, settings, project, verifier pin, stale digests and incomplete receipts. The request API refuses tampered source with an inspectable reason and rejects a foreign-context parent even with a valid prepared release available. |

## Verification and integration handoff

Base ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08. Code commit 3941ca0f02a612046b7b65fd274ab8d9bf428fb3. Compatibility specialist owned the release selector, historical verification-case extraction and selection tests. Request-flow specialist owned the original HTTP/acquisition contract tests. Lead integrated the service, added review regressions, and independently ran checks. Dedicated reviewer examined both areas.

* Base reproduction is in base-reproduction.txt. The outer restricted environment blocked loopback and nested isolation, and a historical fixture omitted a redundant measurement.finding copy. focused-initial.log retains the failures. The corrected path recomputes the finding from raw counts.
* Focused command: python -m unittest -v tests.test_b12_reuse_requests tests.test_b12_reuse_selection tests.test_lab tests.test_followup tests.test_optics tests.test_release_planner tests.test_archive. The real macOS Seatbelt and loopback run passed 51 tests (focused.log). No coding-model request was necessary to exercise reuse. Fresh-generation tests use a fixture coding worker.
* Static checks: python3 -m compileall -q factory tests and git diff --check. Both passed. The existing completed package also passed python -m factory.replay_bundle public/b12/completed.json, reproducing a withheld direct estimate and 32.006829774391655 mg/L corrected follow-up.
* For combined acceptance, seed the known live original direct and prepared source/check records used by RequestReuseTests.seed_live, with a counting worker that raises on every call. Submit POST /api/tasks with {"brief":"Measure B12 at 550 nm","sample_id":"Assay lot C"}. Await the direct above-range finding. POST /api/tasks/{direct}/approve with {"factor":4}. POST /api/tasks/{child}/prepare with {"sample_id":"Assay lot C-4","parent_id":"Assay lot C","sample_ml":0.75,"final_ml":3,"unit":"mL"}. Use the real WO-16 collection and capture the number of follow-up acquisitions. Inject saturation in the simulator follow-up only and POST /api/tasks/{child}/rerun with {}.
* Confirm new direct and child IDs, the original revisions and original provenance with zero worker calls. Reopen the live store and repeat the same empty-body rerun. Assert no new acquisition, unchanged rejected attempt ID/raw bytes/saturation reason/sample lineage/calibration reference, no corrected estimate and no label reveal. Send a bundle claiming this rejection completed to WO-17 archive-only presenter startup and assert refusal. An explicit retry_of request is a different operation. These combined checks are pending.
* Integration owner must import WO-16's record_direct_analysis and wrap the shared Lab.generate call to analyze_direct AFTER successful collection. Record analysis errors with error=error, successful analyzed revisions with revision=record["revision"]. Propagate recording errors; no optional import. WO-16 owns collect/rerun/follow-up and persistence. Lane tests intentionally adapt only collection identity, and verify retry_of forwarding against the caller signature.
* Presenter API and exported evidence report the reuse origin. The existing browser form submits default U-01/2× and labels a selected live run Fresh generation. Renamed/4× controls and browser proof are outside this backend lane. WO-14 is deferred. Re-run local focused, mandatory sandbox, PR CI and combined checks if reviewed head or integration base changes.

## Round 2 — APPROVED

The independent reviewer repeated both round 1 reproductions on the code commit. The foreign parent failed the project and verification comparison. Fabricated sandbox failures failed the required safe-decline proof. Reviewer ran the 27 request, selection and planner tests with native macOS isolation and loopback, and git diff --check. All passed. No further blocking findings. The lead separately ran the larger focused suite. Mandatory combined checks above remain outstanding.

Local full suite on code commit: python -m unittest discover -s tests -v ran 151 in 78.737s, with 10 UV–Vis errors during overlap with other worktrees using the host-wide uvvis-demo-01 instrument. Nine reported the instrument was already in use and the subprocess port-readiness test reported an invalid service origin. This run is non-passing. Full trace is in full-suite.log; the clean-host check is the draft PR's Scientific integration job. An earlier pre-review run passed 146 tests. The Vercel/browser and aggregate scientific jobs on the combined commit remain the integration owner's responsibility.

## Reopened external review of 6a6b9f7 — CHANGES_REQUESTED

1. Changed analysis.py to print('{}'), recomputed task.revision, and kept the recorded worker/checks. The selector accepted the stale verification evidence.
2. Set a known prepared source's parent_revision to 64 zeroes with its valid direct parent present. Selection accepted the nonexistent revision.
3. Moved a saved absorbance from 0.20549174370817358 to the adjacent binary64 value 0.20549174370817355. The valid direct approval failed before dispatch.

## Remediation review — APPROVED

Three specialists handled source binding, prepared lineage and numeric reconstruction. After implementation the precision specialist independently reviewed the two provenance fixes and ran the exact mutations; the binding specialist independently reviewed numeric handling. The lead integrated promotion, evidence propagation, historical fallback and the request-level regressions.

| Finding | Resolution and independent evidence |
| --- | --- |
| Rehashed source and stale checks | New direct and prepared promotions store a b12-verification@1 receipt over revision, checks, original worker and release contract. Selection hashes the same artifact bytes that it returns and compares the receipt. Changing and rehashing source with stale evidence fails; removing the binding never makes that source eligible. See test_b12_verification_binding. |
| Unrelated parent revision | Selection follows the prepared original's parent task, checks its live identity, artifact bytes, revision and provenance, and resolves a reused direct parent to the verified original. It validates the prepared-capability parent report against that source and worker. Missing parent, fabricated parent digest, stale report, incompatible/reused path and cycle probes fail. The normal HTTP/Lab suite also generates a prepared original from a reused direct parent and later reuses it. A distinct-experimental-parent test checks the two receipts separately. |
| Historical float variation | Approval permits one adjacent binary64 value in either direction for each absorbance recomputed with log10. Exact record shape, metadata types/values, raw settings/units, digest, IDs and range verdict still apply. Nextafter-based portable tests cover adjacent and two-step values, materially different readings, missing/nonfinite values and changed calibration or metadata. |

The host writes integrity digests, not signatures against an attacker rewriting every trusted record. An unbound historical record remains readable and can be replayed. A new direct request against an otherwise eligible but unbound catalog builds a separate verified release; it never attaches new provenance to the old source. Explicit null or mismatched receipts fail selection. Test fixtures explicitly bind known checked-in source and verifier data; production never imports the archive as a live release.

For evidence consumers, verification_receipt(revision, checks, worker, contract) hashes canonical JSON of source_revision/checks/worker/contract. validate_receipt(task, files, contract) checks the staged bytes before validating the receipt. The child retains parent_verification for its experimental parent. Reused prepared code also retains origin_parent_task_id, origin_parent_revision, origin_parent_worker, origin_parent_checks and origin_parent_verification. The prepared release_contract is used for both parent reports. A different historical parent's bytes remain in its original live release folder. The two-run bundle retains its reference and the inputs necessary to check its receipt.

The lead ran 64 focused tests with real macOS scientific isolation and loopback, with full output in reopened-focused.log. Commands: python -m unittest -v tests.test_b12_verification_binding tests.test_b12_approval_precision tests.test_b12_reuse_selection tests.test_b12_reuse_requests tests.test_lab tests.test_followup tests.test_optics tests.test_release_planner tests.test_archive; python3 -m compileall -q factory tests; git diff --check. Native Linux execution of the Python rounding test was not available locally. The independent PR workflow runs full science on macOS and production/browser on Linux. Consult PR #18 for exact final-head CI. The shared-collection, restart/saturation and archive-only combined acceptance remain pending. Browser controls/labeling and WO-14 remain outside this lane.
