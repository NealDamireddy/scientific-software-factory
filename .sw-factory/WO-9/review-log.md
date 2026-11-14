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
