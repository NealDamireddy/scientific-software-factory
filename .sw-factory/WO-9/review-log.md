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

## Round 7 — Corrected-signal positivity

Applied the Round 6 change in 67b2db2 and submitted it for independent re-review. On the reviewed implementation, deleting only the corrected-signal positivity guard and re-signing the candidate promoted both releases (51/51 and 47/47). The three published detector triples produced unflagged estimates of 5.157894736842106 mg/L and 8.25 mg/L respectively.

Verifier scientific-release@4 adds one wholly affected group and one group with a single affected replicate. All raw counts are in range. Reversing both corrected signals retains the exact positive transmission ratio, isolating the defect from detector bounds and the logarithm's domain. Against the same candidate, both contracts now fail exactly those two challenges. A good candidate passes 53 concentration checks or 49 time-course checks.

- The retained release withheld the affected concentration and SD, recorded a nonempty review reason and preserved the other rows and their timestamps. Rejection preserved the active pointer, manifest and artifact bytes.
- Full unittest discovery passed 63/63 under macOS Seatbelt in 67.554 seconds. The B12 archive replay withheld U-01 and reproduced 32.006829774391655 mg/L for the twofold follow-up. Compilation and whitespace checks passed. Discovery emitted the pre-existing HTTP and SQLite resource warnings.
- An independent scoped code review verified the challenge ratios, re-signed mutation, group-specific behavior and complete blocked reports, and found no outstanding positivity blocker. PR #4 and WO-9 remain available for independent re-review.

## Round 8 — Independent re-review — APPROVED (work-order scope)

Reviewed PR #4 head `7763601ab7228401d74086351486015839cfff90`, including implementation fix `67b2db29355490aa1a9864f59068136b07b456dc`, author response, and delta from Round 6 evidence commit `1faedf8`. Prior full requirements/blueprints/Knowledge Base alignment review remains applicable; this change adds independent fixtures and regressions without changing the acquisition/planning boundaries. A fresh code reviewer independently examined the fix and relevant verification/promotion paths and found no new issues. The primary reviewer ran full regression verification and independently repeated the original reproduction.

### All recorded blockers closed

- **Corrected-signal positivity:** the exact re-signed mutant missing only `min(blank, sample) <= dark` now fails exactly `negative dark-corrected signals` and `negative dark-corrected signals in one replicate` for both concentration and time_course. No candidate release is published. Original active pointers, loaded manifests and artifact bytes remain identical.
- Independently submitted the original `(dark, blank, sample)` triples `(40000,7232,35904)`, `(40000,7232,37952)`, `(40000,7232,38976)` to retained verified source, with all three readings invalid and with only the last invalid. Each affected result has null concentration/SD and a nonblank review reason; all other rows match the clean retained-release results, preserving timepoint identities. The new fixtures preserve the positive transmission ratios while changing the corrected-signal sign, so rejection is not merely a logarithm error.
- Previously fixed detector-range, finite timing (including signed infinity), timestamp, replicate, units and settings mutation regressions passed again. The fixture expectations remain factory-owned and analytically independent of candidate source/private simulator truth.
- **Report completeness:** independently repeated source-revision failure. Concentration returns 53 outcomes (5 passed, 2 failed, 46 blocked), time_course 49 (5 passed, 2 failed, 42 blocked), with zero candidate executions and unchanged active releases. Blocking dependent checks is correct fail-closed behavior, not a remaining drift defect.

### Independently executed verification

- `python3 -m unittest discover -s tests -v`: **63/63 passed in 57.575 seconds** using real Linux bubblewrap; no mandatory skips or unsafe fallback.
- Passing fixture releases satisfy **53 concentration** and **49 time-course** checks under `scientific-release@4`.
- `python3 -m factory.replay_bundle public/b12/completed.json`: direct U-01 withheld; twofold follow-up **32.006829774391655 mg/L** for the original vial (**16.003414887195827 mg/L** diluted), matching author evidence.
- `python3 -m compileall -q factory tests` and `git diff --check ffb80d1...HEAD`: passed.
- Atomic rollback/history, digest rechecking before execution, compiled recipe equality, public-field projection, denied network/private reads/trusted writes and trusted-data retention regressions passed. Nonzero-intercept calibration, sample SD, alternate samples/calibrations, actual timepoint identity and recorded 1e-7 relative/absolute tolerance remain sound. No additional numerical/publication/isolation blocker found.
- Test-only SQLite ResourceWarnings also seen in prior rounds are nonblocking; product repository operations explicitly close their connections.

### Scope and decision

**Verdict: APPROVED for WO-9's independently testable scope; ready for Neal's approval.** This supersedes the prior changes-requested recommendations. No remaining blocking findings identified. This is evidence for the supported verification contracts, not proof of arbitrary generated-source correctness or physical instrument validation.

WO-6 real persisted context/profile, WO-7 real public acquisition outputs and WO-8 approval/trusted-recipe/worker composition remain recorded downstream integration dependencies, not WO-9 approval blockers. Live end-to-end integration, fresh model generation, planner/reuse, browser presentation and scheduling are not claimed as completed by this review. Current main's integration changes were not folded into the tested PR line.

Only review evidence was appended. No implementation edits, merge, GitHub approval submission or Completed transition. Leave PR open and WO-9 In Review pending the user's decision.

## Round 9 — Final independent merge review

Reviewed PR #4 with WO-6 and WO-7 on main at `505c66b`. WO-7 accepts an integral JSON replicate count such as `3.0`; the verifier rejected it. Commit `3caa11f` uses the upstream settings validator. Commit `ab6ad5e` handles equivalent integer and floating-point optical settings in the candidate's public input. Frozen measurements and exact worker recipe bytes retain their original representation. The regression covers mixed calibration, standard and sample settings, and rejects invalid counts.

Independent probes passed for concentration and time course, original input preservation, and rejection of a changed worker recipe. All 82 discovered tests passed at `ab6ad5e` across two invocations under macOS Seatbelt. Nine acquisition tests encountered a competing local instrument lease during discovery and all nine passed on a separate run. The B12 replay withheld direct U-01 and returned 32.006829774391655 mg/L for the twofold follow-up. Compilation and whitespace checks passed. The independent Linux review previously reproduced both release manifests and the fail-closed prerequisite behavior.

The six original Drift Bot findings and its later prerequisite-reporting comment have evidence replies and are resolved. Final code review approved for WO-9. Live WO-8 composition is downstream.

## Round 10 — Renewed independent review — CHANGES_REQUESTED (post-merge follow-up)

Reviewed current WO-9, AC-APP-002.1–.7, both linked blueprints, their unresolved drift comments, Knowledge Base Plan, PR replies and required CI. Started at `1c2eb04fae9acad5f4eb917a1148c06cb29b5a65`; refreshed after concurrent upstream integration to `cc7a23787354ee3c70f5ea57dd5d65e5e9006428` over `8aa01f0741d56e3d8f80d35a91deffa0028c97c7`. WO-9's verifier/runtime/contract/repository files are unchanged between those two heads. A fresh independent reviewer examined the complete WO-9 change and relevant producer contracts; the primary reviewer independently reproduced the finding on both revisions and reran verification on the final head.

PR #4 was merged externally by NealDamireddy at 2026-11-14T19:55:59Z while this review was running, merge commit `69b6d333fc1a862d5e79a0291fa858c1090063f1`. This reviewer performed no merge or status transition. The finding is now a post-merge correction needed before WO-9 sign-off.

### One blocking P2 finding — missing nonfinite frozen-calibration bound verification

**Dimension:** numerical/input-validation verification; requirements/blueprint alignment. **Anchors:** `factory/scientific_contract.py:213–217` and `factory/scientific_analysis.py:127–143`. The time-course contract challenges zero slope and reversed range but never NaN/infinite frozen bounds. The runtime accepts calibration bounds in its caller payload and checks settings/output finiteness, not bound finiteness or approved calibration digest identity.

Actual Linux bubblewrap reproduction in temporary repositories:

1. Promote the original time-course fixture and retain its release ID.
2. Remove only low/high finiteness validation from the candidate: retain `finite(...)` for slope/intercept, read low/high directly, and make the final `math.isfinite` guard check slope/intercept only. Keep positive slope, ordered range, all measurement guards, OLS/estimation and error handling unchanged. Re-sign artifact/source metadata.
3. The deficient candidate passes **49/49 checks**, publishes and replaces the previous active release.
4. Analyze the clean independent time-course fixture with only calibration.high changed to `NaN`, then `+Infinity`. The promoted mutant returns **8.25 mg/L**, sample SD **2.5000000000000004**, and review_reason=null in both cases. The original candidate withholds the same inputs with `Invalid calibration: high must be a finite number`.

This is an ordinary missing validation guard, not fixture-specific overfitting. It demonstrates a gap in WO-9's explicitly scoped finite-value/calibration-range verification. **Correction:** add independent nonfinite low/high challenges (NaN and signed infinity), require withheld estimates/SD with review reasons, and add a re-signed bound-validation mutation regression proving rejection and unchanged prior active pointer/manifest/artifacts. Exercise both original retained source and deficient-source certification.

**Impact limitation:** WO-8's normal approval path validates the stored frozen calibration's digest, settings and finite slope/intercept/bounds (`factory/specifications.py:105–121`). These malformed-bound inputs do not pass that approval boundary. This is **not a demonstrated bypass of the approved production workflow**, and the original fixture already handles invalid bounds correctly. Severity is P2, not P1. The independent WO-9 gate nevertheless certifies deficient source, and standalone `analyze_release` does not enforce a validated/digest-bound calibration precondition. Passing upstream validation/handoff does not exercise this missing negative contract case.

### Independently corroborated evidence

- On initial head 1c2eb04, full discovery passed **82/82 in 59.134s** under Linux bubblewrap in one invocation.
- On refreshed final head cc7a237, `python3 -m unittest discover -s tests -v` passed **103/103 in 60.360s**, including real saved-context acquisition and all previous detector/timing/positivity/units/settings/provenance mutation, rollback/history/digest/isolation regressions. No unsafe fallback or mandatory-check skip.
- `python3 scripts/check_wo8_wo9_handoff.py HEAD HEAD` passed against cc7a237 for both refs: real specification/planner/verifier/repository with fixture worker, **53 concentration / 49 time-course checks** under scientific-release@5. Both sample-only changes reused the same source/release with **zero additional worker calls**. Concentration release `3088c169a8a5628071eb59cd6aa99790f0cbed95d87bcfc7cecb1fd030b33bbb`; time-course release `b4d4308b9ea5ec23b76bd820091cad94b47750f33f105f5217f97a4e1cbe6131`.
- B12 replay on both reviewed heads reproduced direct U-01 withheld and twofold follow-up **32.006829774391655 mg/L** for the original vial (16.003414887195827 mg/L diluted). Compilation/whitespace checks passed.
- Numerical fixture references remain public-count based with nonzero intercept, sample SD, alternate calibrations/sample identities, actual timepoint identities and recorded 1e-7 relative/absolute tolerance. No new OLS/SD/isolation/publication-transaction defect found. Original report-completeness and positivity findings remain fixed.
- Independently read the earlier CI failure log: 1c2eb04's handoff step failed because the WO-8 script was absent, not because scoped tests failed. Final cc7a237 includes that upstream script; both required GitHub checks are **green** in run `43634257666`. Production browser verification is supporting hosted/static evidence, not proof against the new calibration mutation. The renewed finding exists despite passing CI.

### Scope and work-order recommendation

Planner/generation/reuse drift comments concern APP-001/003 ownership, not missing WO-9 scope. WO-6/7/8 handoffs are not treated as blockers; their composition now has independent fixture-worker evidence. No fresh model generation, scheduler/browser completion, kinetic inference or physical validation is required for this finding. Existing CI conditional-gate concerns are separate workflow ownership; native sandbox failures were not skipped in either tested suite.

**Verdict:** one new P2 verification issue; hold WO-9 sign-off pending correction. This revises the earlier approval-readiness recommendation based on newly reproduced evidence; it does not reopen the fixed prior findings. Since PR #4 merged externally during review, implement a follow-up correction rather than representing the merged PR as awaiting merge. WO-9 remained In Review at the final record read. Only review evidence was appended on the original working branch; no implementation edits, main-branch edits, formal approval or Completed transition.
