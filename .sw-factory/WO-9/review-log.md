# WO-9 review log

## Round 1 — CHANGES_REQUESTED

Three reviewers examined the release/repository boundary and its tests, the analysis runtime and independently written fixture candidate, and the numerical contract. They reviewed the changes against origin/main through 31b42b5.

- Blocking, requirements and provenance. Reusing the experiment-kind variable while iterating lab/project headers rejected valid release scopes. The verifier now checks the original experiment type. A negative test supplies a mismatched scope.
- Blocking, host resource limits. A failed artifact size check still allowed the subsequent display/recipe checks to parse the oversized bytes. Both parsers now enforce the limit before decoding.
- Blocking, scientific provenance. A missing blank on both the calibration and readings could compare equal. The fixture candidate also accepted missing measurement schema/job/model provenance and could pool replicates across different jobs. Add independent malformed fixtures and repeat the review.
- The numerical reference reviewer independently recomputed the OLS coefficients, concentration estimates and sample deviations and verified the irregular measurement timestamps and comparison tolerance.
- The repository reviewer found the transaction and rollback paths sound. The runtime reviewer confirmed public-field projection and isolated execution.
