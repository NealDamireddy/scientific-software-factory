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

## Round 2 — executable publication and upgrade regressions

The follow-up began at f4b755d7a78c8c4d974ad6bc64f75f004b6aba12. WO-15 was already In Review and PR #14 was open for review. The lead supervised two implementation engineers and an independent reviewer. Changes are limited to tests, the historical test input and the execution record.

**P2, AC-APP-002.1/.2/.6.** The publication suite now re-signs the exact sanitizer previously exercised by the reviewer (source revision d2a472cf25d32dd30ea893f71c71b6eb3761d913bf376face48d45c76f36023d). It substitutes finite fixture values for nonfinite slope, intercept, low or high. The pinned-base verifier promoted this source after 49/49 checks. On the current branch the valid active release passed 64/64. The sanitizer failed exactly the twelve field/value combinations, passed all other 52 checks, and produced zero blocked checks and no release ID. Reopening SQLite preserved the active pointer, raw manifest and every blob. The complete Seatbelt publication report includes the signed input metadata, each verdict and the before/after release identity. [Publication regression](../../tests/test_frozen_calibration_publication.py) · [Full report](sanitizer-publication.json)

**P3, historical compatibility.** Restoring a genuine @5 SQLite logical dump allows ordinary test discovery on shallow checkouts. The capture utility runs the existing handoff on a clean checkout of ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08. Both experiments have original approvals, preparations, digest-verified manifests, source files and active pointers. The 16,010-byte gzip fixture has SHA-256 870a48bbf2ef27927025d8eae3fdf20735ff738be185ba1790c51bf72cf0f10e. The capture includes SQLite's persisted schema version. An initial capture missing that value failed setup and was replaced. [Upgrade regression](../../tests/test_frozen_calibration_upgrade.py) · [Fixture capture procedure](../../tests/fixtures/wo15/capture.py)

The test replans the original time-course approval, proves its @5 release stays active through candidate preparation, and requires reverification of the same artifact bytes before the new release becomes active. The original task and release remain readable. Fresh sample-only approvals then reuse the certified time-course source and historical @5 concentration source with zero worker calls. Only the coding worker is a fixture; the planner, SQLite repositories, publisher and offline execution are real.

**Sensitivity checks.** Removing just the negative-infinite-intercept challenge made the sanitizer regression fail. Reverting the planner's revision-aware preparation ID returned the old completed task for the same approval and failed the upgrade test. Disabling the compatibility rejection alone returned a reused release and also failed the test. The historical concentration control passed under the task-ID reversion.

**Verdict — APPROVED.** The lead and independent reviewer ran the two new regressions with the existing frozen-calibration and planner suites using Python 3.14.6, jsonschema 4.26.0 and macOS Seatbelt. All 14 tests passed in 28.145 s and 28.050 s respectively. Run `python3 -B -m unittest -v tests.test_frozen_calibration_publication tests.test_frozen_calibration_upgrade tests.test_frozen_calibration tests.test_release_planner`. Python compilation and whitespace checks passed. Final-head CI and the exact reviewed commit are linked on PR #14. Combined-tree verification and WO-14 remain separate.
