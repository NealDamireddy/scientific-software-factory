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
