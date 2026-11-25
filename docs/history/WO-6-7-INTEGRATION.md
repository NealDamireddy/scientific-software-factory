# WO-6 and WO-7 integration verification

Both implementation heads were merged into a dedicated branch from `main` at `ffb80d1`. The prepared SQLite context and the loopback simulator use one public profile. [WO-6 implementation (c7755e5)](https://github.com/NealDamireddy/scientific-software-factory/pull/2) · [WO-7 implementation (757c68d)](https://github.com/NealDamireddy/scientific-software-factory/pull/3)

## Acceptance evidence

| 8090 criteria in scope | Checks on the integration branch |
| --- | --- |
| AC-CTX-001.1–001.5, AC-CTX-002.6 | Validated required fields and profile pins, rejected cross-lab references, shared an instrument between projects, restored immutable historical revisions after reopen and rejected a competing stale write. |
| AC-VIS-001.1–001.4 | Compared live capabilities with the public registry profile, verified simulated provenance, rejected unsupported settings and reported an unavailable service. |
| AC-VIS-002.1–002.4 | Created a new job with a compatible blank, checked each sample and replicate, rejected incompatible references and conflicting submission keys, and recovered the same job after a lost response. |
| AC-VIS-002.5–002.7 | Verified cancellation, process interruption, partial records, exclusive execution and exclusion of private model data from public responses. |

All three Draft 2020-12 schemas passed validation. The service advertised `uvvis-demo-01`, owned by `demo-lab`, with profile `virtual-uvvis@1`, version 1. The projection has 450, 550 and 650 nm channels, a 10 mm path, 1–10 replicates, the `measure-absorbance` operation, a required blank and simulated provenance. Its canonical UTF-8 JSON SHA-256 matched the persisted lab instance, the live response and the measurement records: `d441df2219b76210b43c95cbd8f57758b68d3bfb772c343e85e3af67a3d23286`. [WO-6](https://factory.8090.ai/project/57fbf0e2-015b-4e28-93cd-ae06b55fadc4/work-orders/6) · [WO-7](https://factory.8090.ai/project/57fbf0e2-015b-4e28-93cd-ae06b55fadc4/work-orders/7)

## Integration findings and regressions

**AC-VIS-002.4, equivalent retries.** SQLite preserves an integral JSON count such as `3.0`. The service validates incoming settings and normalizes the integer fields before recording a new acquisition. It compares a retry with the decoded saved request, so older SQLite records containing `3.0` also match a retry containing `3`. The HTTP regression verifies one job, the original three readings after restart, and HTTP 409 for a genuinely changed count.

**AC-VIS-002.7, exclusive instrument ownership.** Each simulator now claims its instrument ID at startup with a nonblocking OS lock keyed by the SHA-256 of the instance ID in the host’s shared `/tmp`. It holds the lock for the service lifetime. A separate store lock protects crash reconciliation. In the two-process regression, the first process held an active job. The second process, using another store, was refused the same ID and could open a different ID. Killing the owner released the lock and a replacement acquired successfully.

Both regressions reproduced the reported failures at `c9a6d3a` and passed after the fixes.

## Local execution on November 14, 2026

- **Combined suite:** 70 tests passed, including the two review regressions, the saved-profile handoff and the existing B12 suite.
- **Fresh acquisition:** A temporary harness reopened revision 1 of `demo-lab/visible-assay` (SHA-256 `e23f2d62393216c68360c698fed97ef3b88ecc818901b6bece330524454932d6`) after saving revision 2 at 450 nm. Revision 1 supplied the instrument, sample IDs, 650 nm setting, 10 mm path and triplicate count. A separate simulator process started with an empty job store. Job `10e381ac7b5047358525c73e0ae41e92` and blank `c589fabd3b794781b4a5732b57b1323f` produced 12 timestamped readings for three standards and one unknown. The unknown's three raw counts were 45815, 45824 and 45816. Retrying returned the same job and records.
- **Crash recovery:** A second simulator process was killed after its first replicate. After restart, retrying returned the original job `13e4bc08c14e448f8bd33c026e98c853` as interrupted with its single incomplete reading.
- **B12:** The archived direct sample again required review. The diluted follow-up reproduced 32.006829774391655 mg/L. Held-out panel MAE was 0.00554009 mg/L and published-data MAE was 4.71979727 mg/L.

Run from the repository root on a host with a working scientific sandbox and loopback access. Use a new directory for each benchmark report.

```sh
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python -m unittest tests.test_uvvis_profile_handoff
uv run --frozen python -m factory.assays.b12.replay_bundle public/b12/completed.json
uv run --frozen python -m factory.assays.b12.benchmark public/b12/completed.json --out runs/integration-b12-evaluation
```

## Outstanding review and downstream dependency

The two component interfaces passed their scoped acceptance checks. The saved-project smoke exercised the trusted adapter directly in a test harness. Persisting approval for the exact specification digest and compiling the authorized acquisition recipe through the application service remain assigned to WO-8. The integration PR awaits review. [WO-8](https://factory.8090.ai/project/57fbf0e2-015b-4e28-93cd-ae06b55fadc4/work-orders/8)
