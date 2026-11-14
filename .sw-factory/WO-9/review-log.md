# WO-9 review log

## Round 1 — CHANGES_REQUESTED

Three reviewers examined the release/repository boundary and its tests, the analysis runtime and independently written fixture candidate, and the numerical contract. They reviewed the changes against origin/main through 31b42b5.

- Blocking, requirements and provenance. Reusing the experiment-kind variable while iterating lab/project headers rejected valid release scopes. The verifier now checks the original experiment type. A negative test supplies a mismatched scope.
- Blocking, host resource limits. A failed artifact size check still allowed the subsequent display/recipe checks to parse the oversized bytes. Both parsers now enforce the limit before decoding.
- Blocking, scientific provenance. A missing blank on both the calibration and readings could compare equal. The fixture candidate also accepted missing measurement schema/job/model provenance and could pool replicates across different jobs. Add independent malformed fixtures and repeat the review.
- The numerical reference reviewer independently recomputed the OLS coefficients, concentration estimates and sample deviations and verified the irregular measurement timestamps and comparison tolerance.
- The repository reviewer found the transaction and rollback paths sound. The runtime reviewer confirmed public-field projection and isolated execution.

## Round 2 — APPROVED

Reviewers re-examined the full change from origin/main through e5e2c77. All three review areas received approval with zero remaining blocking or advisory findings.

- Requirements and architecture. Both experiment types pass their independent contract suites, identify source and context, reject malformed provenance, and preserve the active release on failure. The public profile, raw records and trusted recipe enter through the upstream contract boundaries.
- Numerical review. Independently checked the OLS reference, inclusive endpoints, singleton and repeated measurements, irregular UTC timestamps and targeted review rows. There are 30 concentration and 26 time-course scientific challenges. Both absolute and relative tolerance are 1e-7.
- Runtime and data safety. The candidate sees projected public fields through sandbox stdin. Invalid blank references, absent or inconsistent job/model provenance, unsupported schemas, setting mismatches and out-of-range inputs are covered. Real sandbox probes exercised network, private read and trusted-file write denial.
- Persistence. Reopening, repeated promotion, immutable history, tamper detection and an injected transaction failure passed against temporary SQLite repositories.
- Execution evidence. The full command `python -m unittest discover -s tests -v` passed all 59 tests under macOS Seatbelt in 16.109 seconds. The explicit `python -m factory.replay_bundle public/b12/completed.json` replay reproduced the direct review and 32.006829774391655 mg/L follow-up.
- Exploratory pass. Published both fixture candidates, reloaded their manifests and analyzed public counts through the retained release. The concentration release passed 38 checks and returned 5.157895 mg/L with sample SD 1.473684 for copper-14. The time-course release passed 34 checks and returned 8.25 mg/L with SD 2.5 at 2026-02-03T14:05:07.375000+00:00. The bad-candidate and rollback tests preserved prior releases.
- Build health. Whitespace and Python compilation checks passed. This backend-only change has no browser surface. End-to-end acquisition with the real WO-8 compiler remains an upstream integration milestone.

**Verdict** APPROVED

## Round 3 — Independent work-order review — CHANGES_REQUESTED

Reviewed 2026-11-14 against PR #4 head `c3ab3f1cff1082ab4bcc1c3605281fc0378f823e`, merge base/main `ffb80d175e02ed83b07b298d0b3f82d86b4ecbd4`. Compared WO-9 scope and AC-APP-002.1–.7 with both linked blueprints, the scientific-app requirements, and Knowledge Base Plan. A separate reviewer audited promotion/provenance/reporting; the primary reviewer independently examined numerical contracts, runtime and regression evidence. Drift Bot/Vercel success is not numerical or sandbox certification.

### Blocking findings

1. **Numerical/input-validation verification — release gate admits candidates missing required validation.** `factory/scientific_contract.py:99–177`, `factory/scientific_analysis.py:123–136`. The fixture candidate contains detector-range and elapsed-time guards, but the independent verifier never challenges their removal. In temporary repositories, removing only the two-line detector integer/range check (`tests/fixtures/scientific_analysis.py:54–55`) and re-signing its artifact/source metadata promoted both concentration (38/38) and time-course (34/34) releases. Shifting one reading's dark/blank/sample counts down by `dark_counts + 1` preserves transmission but makes dark_counts=-1. The promoted concentration release returned 5.157894736842106 mg/L (SD 1.4736842105263164) and the time-course release returned 8.25 mg/L (SD 2.5000000000000004), both without review reasons. Separately, removing only the two-line elapsed-time validation (`tests/fixtures/scientific_analysis.py:47–48`) promoted a 34/34 time-course release that accepted elapsed_s=NaN and returned 8.25 mg/L without review. Candidate execution used the real offline sandbox throughout; mutations were in memory only, not repository edits. This is a verification-authority defect, not a claim that the original fixture candidate lacks those guards. It conflicts with AC-APP-002.1/.6 and the blueprint's invalid-count/provenance contracts. Add independent cases for negative/noninteger/saturated detector counts and nonfinite/negative timing, and tests proving such deficient candidates cannot replace the active release. Also cover missing/malformed UTC timestamps and repeated/invalid replicate identities, which currently have candidate guards but no independent negative challenge. Retain unaffected sample/timepoint results.

2. **Requirements alignment/report completeness — prerequisite failures silently omit applicable checks.** `factory/scientific_release.py:174–188`. For supported time_course with valid compiled recipe, setting candidate.source_revision='bad' returns seven checks but omits the isolation check and all 26 scientific checks. Concentration similarly omits 30 scientific checks. Rejection is safe, but AC-APP-002.1 requires each applicable check to be reported. Enumerate blocked/not-run checks with explicit prerequisite reasons rather than executing unsafe bytes or silently omitting checks. Extend the malformed-metadata tests to assert report completeness and preservation of the previous release.

### Independently verified evidence

- With declared jsonschema==4.26.0 and Linux bubblewrap installed in the review runner, `python3 -m unittest discover -s tests -v` passed **59/59** in 14.117 seconds. Initial missing-dependency/sandbox failures were runner prerequisites, not product regressions. No unsafe fallback or skipped mandatory safety checks was used.
- `python3 -m factory.replay_bundle public/b12/completed.json` reproduced U-01 withheld for review and the 2x follow-up original concentration **32.006829774391655 mg/L** (diluted 16.003414887195827 mg/L), matching the author's evidence.
- `python3 -m compileall -q factory tests` and `git diff --check origin/main...HEAD` passed. This backend-only slice has no changed browser surface; Vercel is supporting frontend build evidence, not a Python verification gate.
- Independently recomputed the OLS normal equations from raw dark-corrected counts: concentration slope 0.20427035420055867, intercept 0.1505149978319904; copper-14 mean 5.157894736842106, sample SD 1.473684210526316. Expected references match within the recorded rel_tol=abs_tol=1e-7. Alternate calibration, sample IDs, singleton SD, inclusive endpoints and irregular first-replicate UTC timepoint identities are sound. Fixtures use public counts, not hidden truth; no kinetics or physical-validation claim is made.
- Atomic SQLite rollback, historical release retrieval, repeated publication, digest rechecking before execution, project-scoped pointers, recipe equality, public-field projection and real isolation probes passed. No separate transaction/publication blocker was found. The safety and B12 claims are corroborated; a passing finite fixture corpus does not establish all required validation behavior.

### Downstream dependencies — not WO-9 approval blockers

- **WO-6:** consume its canonical profile and real persisted lab/project/instrument revision/digest projection after integration.
- **WO-7:** consume actual public measurement/settings schemas and live compatible blank/job records; re-run the verifier/runtime contract against those outputs without simulator-private truth.
- **WO-8:** bind approvals to exact specification and pinned context, supply trusted compiled recipes and real candidate/worker receipts, and own the approved-context-to-fresh-acquisition composition path. Generation planning and compatibility/reuse are explicitly outside WO-9.
- Complete live acquisition-to-release composition after these interfaces are available; scheduling/evidence/CI ownership remains with the downstream orders. No live model generation, browser workflow or unfinished integration functionality is required to resolve the two scoped findings.

**Work-order verdict:** not ready for approval; CHANGES_REQUESTED for the two independently reproducible WO-9 findings. Preserve In Review. No implementation changes, merge, formal approval or Completed transition was performed. This round supersedes Round 2's approval recommendation for the reviewed implementation.

## Round 4 — Remediation submitted for re-review

Implementation commit aa8fc4d addresses both Round 3 findings. The independent code review of the remediation found no remaining blockers in the two reviewed areas. Formal work-order re-review remains pending.

1. The verifier adds eleven challenges per experiment type. Uniform offsets make raw detector counts negative, fractional or saturated while preserving the transmission ratio. The other challenges supply NaN or negative elapsed time, missing/malformed/non-UTC timestamps, and repeated/nonpositive/fractional replicate IDs. Each case requires the affected group to withhold its estimate with a reason and preserves the other groups' expected results. All previous 56 scientific fixture/reference pairs were retained.
2. The check catalogue can be enumerated before a recipe is safe to use. Each check records passed, failed or blocked and retains its boolean passed field. The manifest identifies the updated verifier as scientific-release@2. A bad source revision produced 49 concentration outcomes (5 passed, 2 failed, 42 blocked) and 45 time-course outcomes (5 passed, 2 failed, 38 blocked). Both reports named the prerequisite, retained the prior release and ran no candidate bytes. Tests also cover incomplete recipes, failed snapshots and unavailable isolation.

### Verification on macOS Seatbelt

- Full unittest discovery passed 61/61 in 40.982 seconds. The eight re-signed candidate mutations removed one guard at a time from each experiment type, failed the named checks and left the previous active pointer, manifest and bytes intact.
- A separate run of the B12 archive, benchmark, follow-up, lab, optics, replay and sandbox modules passed 29/29. The committed B12 bundle replay withheld the direct U-01 estimate and reproduced the twofold follow-up at 32.006829774391655 mg/L for the original vial.
- Python compilation and Git whitespace checks passed. Scientific fixtures and temporary repositories were used throughout. WO-6/7/8 integration remains a separate handoff.

## Round 5 — Six Drift Bot threads

Retested the six inline findings on bb04a5a. All 61 existing tests passed under Seatbelt. A re-signed candidate that screened out NaN and negative elapsed time could still accept positive infinity, returning 5.157894736842106 mg/L or 8.25 mg/L in the two contracts. The release gate admitted that candidate in both temporary repositories.

Commit 5edcc8b adds signed-infinity fixtures and identifies the verifier as scientific-release@3. The same candidate failed exactly the positive-infinity challenge in each contract, and the prior release remained active. Removing measurement unit validation failed the unit challenge. Removing settings validation failed wavelength, path length and identity checks. Removing detector, elapsed-time, timestamp and replicate guards independently continued to fail their respective challenges. The regression exercises fourteen altered candidates across the two contracts.

A bad source revision or missing pinned recipe produced a complete report with 51 concentration or 47 time-course outcomes. The respective blocked counts were 44 and 40, with zero candidate executions. Fixtures derive their pins from the trusted recipe. Isolation, frozen-calibration digest and active-release preservation tests passed.

Full unittest discovery passed 62/62 under macOS Seatbelt in 57.070 seconds. The B12 replay withheld U-01 and reproduced the 2× follow-up at 32.006829774391655 mg/L. Compilation and whitespace checks passed. Independent code review of the fix found no blockers. Formal PR and WO-9 re-review remain pending.

## Round 6 — Final independent re-review — CHANGES_REQUESTED

Reviewed PR #4 implementation head `907a4f4afecb4d09285a1418f9ffbb8c4d5dbc5d` and the complete change from merge base `ffb80d175e02ed83b07b298d0b3f82d86b4ecbd4`, plus the six author inline replies and latest Drift Bot thread. Rechecked current WO-9/requirements, both linked blueprints and Knowledge Base Plan. A fresh reviewer examined the full implementation; the primary reviewer independently ran the suite and reproduced the new finding below.

### Prior findings and replies

- **Round 3 detector-range/elapsed-time coverage finding addressed.** Real sandboxed mutation regressions now reject candidates omitting detector range, elapsed time, UTC timestamp, replicate identity, detector units or measurement settings, and preserve active release/history. The selective positive-infinity candidate is also rejected in both contracts.
- **Round 3 report-completeness finding addressed.** Bad source revision produces all 51 concentration outcomes (5 passed, 2 failed, 44 blocked) or 47 time-course outcomes (5 passed, 2 failed, 40 blocked), with zero candidate executions. Failed snapshots, invalid trusted recipes and unavailable isolation are covered.
- **Latest Drift Bot blocked-check objection is not a blocker.** A blocked outcome reports an applicable check and its failed prerequisite; it does not claim a pass. Candidate bytes must not execute after integrity/context/isolation failure. Guessing replacement settings or claiming guard-specific results without execution would weaken the trusted boundary. The author response is supported by the implementation and independently passing tests.

### One new blocking finding

**[P1] Numerical/input-validation verification: independent fixtures do not establish positive dark-corrected blank/sample signals.** Anchor `factory/scientific_contract.py:155`; guard-removal coverage `tests/test_scientific_mutations.py:14–29`. The current dark-corrected-transmission case sets sample_counts equal to dark_counts. The logarithm itself rejects zero transmission even when the candidate lacks a positivity check, so this case cannot detect omission of that guard.

Reproduced twice with actual Linux bubblewrap execution and temporary repositories: promote the original fixture, remove only `if min(blank, sample) <= dark: raise ValueError("Dark-corrected blank and sample must be positive")` from the candidate bytes, re-sign artifact/source metadata and verify. The altered candidate passes **51/51 concentration** and **47/47 time-course** checks and **replaces the previous active release**.

For the first sample group, use raw `(dark_counts, blank_counts, sample_counts)` triples `(40000, 7232, 35904)`, `(40000, 7232, 37952)`, `(40000, 7232, 38976)`, leaving public provenance/settings unchanged. All raw counts are nonnegative integers below saturation, but both dark-corrected signals are negative. Their ratios are 1/8, 1/16 and 1/32, producing apparently valid in-range absorbances. The original candidate withholds these records with a review reason. The promoted mutant returns **5.157894736842106 mg/L, SD 1.4736842105263164** for concentration or **8.25 mg/L, SD 2.5000000000000004** for time course, both with review_reason=null. Other groups are unchanged.

This is a verifier coverage defect admitting scientifically invalid measurements, not a claim that the original fixture candidate is missing its guard. It is within WO-9 invalid-count/calibration safety and blueprint validation scope, independent of acquisition integration. Add an independent double-negative dark-corrected-signal challenge (including a bad replicate among valid ones), require the affected estimate/SD to be null with a review reason while other groups survive, and add a re-signed positivity-guard mutation regression that fails promotion and preserves the original active pointer/manifest/bytes. Existing zero/one-negative/zero-blank signal cases should remain covered. No implementation fixes were made during this review.

### Independent verification and safety assessment

- `python3 -m unittest discover -s tests -v`: **62/62 passed in 48.455 seconds** under real Linux bubblewrap; no sandbox bypasses or mandatory-check skips.
- `python3 -m factory.replay_bundle public/b12/completed.json`: direct U-01 withheld; 2x follow-up reproduced **32.006829774391655 mg/L** (diluted **16.003414887195827 mg/L**).
- `python3 -m compileall -q factory tests` and `git diff --check ffb80d1...HEAD` passed.
- Independent numerical oracle remains nonzero-intercept/public-count based, with sample SD, alternate calibrations, actual timepoint identity, unaffected-group preservation and recorded 1e-7 relative/absolute tolerance. The new defect is specifically a physical-input-domain blind spot, not faulty OLS/SD math.
- Atomic rollback, immutable historical retrieval, digest rechecks, compiled recipe equality, public-only projection and sandbox denial/trusted-file evidence remain sound. No additional transaction/isolation blocker found. Passing the suite corroborates the author's regression report but does not cover the demonstrated positivity omission.
- Backend-only change: no new browser surface. Vercel build and Drift Bot are supporting signals, not independent numerical certification.

WO-6 canonical/persisted context, WO-7 actual public acquisitions and WO-8 approvals/trusted recipe/real worker handoff remain separately recorded integration dependencies, not WO-9 approval blockers. Review is scoped to the PR line; current main's newly merged WO-6/7 integration is not claimed to have been retested here. No live model or unfinished browser/scheduling functionality is required to close this finding.

**Final work-order verdict:** CHANGES_REQUESTED; not yet ready for approval because of the one reproduced positivity-verification gap. The two original blockers are closed. Preserve In Review. No merge, formal approval or Completed transition; only review evidence was appended.
