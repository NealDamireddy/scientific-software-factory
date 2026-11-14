# WO-15 review and verification

Reviewed implementation `877aa3679ec0b1ae98dcccebf1ae8e94238723d4` against `ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08`. The final evidence-only commit is identified by the draft PR head. [Draft PR #14](https://github.com/NealDamireddy/scientific-software-factory/pull/14)

## Round 1 — APPROVED

The lead owned contract changes, projection, planner compatibility and integration. A read-only boundary audit traced the WO-8 approval and WO-10 freeze paths. A second engineer owned the pinned-base reproduction, signed publication regression and publication evidence. An independent reviewer inspected the four production files, three test files and execution evidence, repeated the focused tests, and submitted an additional signed mutant. The lead inspected the contributions and repeated the focused checks. The reviewer found zero blocking or advisory findings.

## Acceptance evidence

| REQ-APP-002 criterion | Branch evidence |
| --- | --- |
| .1 Complete report | Each valid or deficient time-course submission produced the same ordered 64 applicable checks. Selective defects failed only their named checks. The existing blocked-report regression verifies the full set when isolation, pins, snapshot or source are unavailable. |
| .2 Preserve release | At base, each of five correctly re-signed deficient candidates displaced a valid 49/49 release. On the branch the baseline passed 64/64. All five mutants reached execution, passed their digest/receipt checks and returned no release ID. Reopened storage preserved the active key, SHA-256-verified manifest and all three original files. |
| .3 Publish valid releases | A valid time-course candidate published under scientific-release@6 with time_course@1, input/output schemas, tolerance, artifact digests, source receipt and context. The real approved planner-to-publisher handoff passed for both experiment types. |
| .5 Frozen fit at actual times | Conflicting valid standards distinguish the referenced estimate of 8.25 mg/L and sample SD of 2.5 from a refit of 5.157894736842106 and 1.4736842105263164. The valid source returned the frozen values, group identities and actual timestamps. Retained-release execution rejects unsupported standards before running source. |
| .6 Invalid estimates withheld | Twelve single-field nonfinite inputs withhold every concentration and SD with a nonempty review reason. The independent reviewer also submitted a re-signed source that replaced every nonfinite coefficient/bound with the valid fixture value. Exactly these twelve checks failed (52 passed, zero blocked). Finite alternate fit, both closed endpoints, equal/reversed bounds, zero/negative slope and isolated above/below-range errors are covered. Existing tests cover units/settings and intact unaffected groups. |
| .7 Deny unauthorized access | The real macOS Seatbelt isolation probe denied outbound network, hidden sample reads and calibration/verification writes and checked the sentinel bytes. Existing tests exercised hostile candidate writes and missing-isolation blockage. |

[Publication evidence with source, pointer, manifest and blob digests](publication-evidence.json). The five mutants use the same source revisions before and after the change. The unguarded candidate failed five checks, each of the selective slope/lower-bound/upper-bound/refit candidates failed one. In the independent reviewer’s extra mutation, source `d2a472cf25d32dd30ea893f71c71b6eb3761d913bf376face48d45c76f36023d` left the original active release `86604cafb4296416f6a1aa3e75c579568e94192f2770aee25adbd99f305b3baa` intact.

## Verification runs

Python 3.14.6 and jsonschema 4.26.0, macOS Seatbelt. The worker supplied fixture source. The verifier, sandbox, repository, specification approvals and planner were real.

- `python3 -m unittest discover -s tests -v` — 136/136 passed in 111.695 s during development, including scheduler composition, specifications, B12 regressions and both scientific release suites. Existing HTTP/SQLite ResourceWarnings appeared. Local log: runs/wo-15/full-suite.log.
- `python3 -m unittest -v tests.test_frozen_calibration tests.test_frozen_calibration_publication tests.test_release_planner` — 12/12 passed in 19.744 s on the reviewed implementation. Independent reviewer reran with `-B` and passed 12/12 in 19.788 s.
- `python3 scripts/check_wo8_wo9_handoff.py HEAD HEAD` — both refs 877aa3679ec0b1ae98dcccebf1ae8e94238723d4. Actual specification approval, preparation, verification, immutable publication and sample-only reuse passed. Concentration passed 53 checks and time course passed 64. Both reused with zero worker calls. Local structured report: runs/wo-15/handoff.json.
- `python3 -m factory.replay_bundle public/b12/completed.json` — direct vial withheld, twofold result 32.006829774391655 mg/L and measured diluted sample 16.003414887195827 mg/L.
- `python3 -m factory.benchmark public/b12/completed.json --out runs/wo-15/b12-benchmark` — blind and published comparison MAEs 0.005540089277148219 and 4.71979727233034 mg/L.
- `python3 -m compileall -q factory tests` and `git diff --check` passed. No separate Python lint/type gate is configured.
- Cross-version exploratory check used separate interpreters against the base and branch trees with the same SQLite databases. Both historical manifests and their digested artifacts reopened. Replanning the identical time-course approval required reverification and then reused the newly certified source. A sample-only edit reused the old concentration release with zero worker calls. [Upgrade digests and worker counts](upgrade-evidence.json)

## Failed attempts and limits

- The first restricted-runner attempt could not start Seatbelt (exit 71). Its base report recorded 7 passed, 1 failed and 41 blocked. Successful runs above used host-supported Seatbelt with isolation active.
- The first cross-version test setup omitted fixtures/context/demo.json from the base export. Including the pinned fixture allowed the real migration check to run. An interim planner fixture test modified a manifest after calculating its fake digest and failed its release-ID assertion. Recording the historical verifier revision before computing its digest corrected the fixture.
- CI on the draft PR covers this lane. The integration owner must repeat the supported-sandbox Python suite, saved-context acquisition, planner-to-publisher/reuse, scheduler composition, B12 replay/benchmark, EPR checks, production build and browser tests on the combined tree. Reopen verification on any base or reviewed-head change. WO-14's live rehearsal follows integration.
- Automatic approval review kept the Software Factory status in Backlog. The PR is linked to the work order and available for independent evaluation.
