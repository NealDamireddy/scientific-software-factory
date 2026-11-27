# Independent input-parity audit

Audited 2026-11-26. **All four separately launched local variants used identical pinned analytical inputs and report identical checked outcomes. Complete receipt/evidence equivalence is not established by the current outcome projection.** No instrument measurements or hosted-cloud equivalence are established.

## Exact inputs

Independently recomputed SHA-256 from bytes, without calling the harness hash helpers:

- Workload: `22adbb480970b1b8e0c11b0c4ff1681e6b085bf27a9f6b38ce20d16986b07282`.
- Common runner: `cab9b87b4b2cdfdc7f41fcc8a05bdeaec2798e3a8511d0414086869d026ae288`.
- All eight source-file hashes in [manifest.json](../fixtures/manifest.json) match both the checkout and `git show 62badef1d608d94903da475bfd2b689cb80f9c49:lab-factory/<file>`.
- Embedded protocol/CSV bytes also match: caffeine 1,117/220 bytes; density 747/129 bytes. CSVs contain eight/three data rows, respectively, including two unknowns each.
- Canonically serialized artifacts reproduce every manifest digest: wrong `6e2d4e0507e25d38829986a12ea441ff726aa99cf7d1187cbd5cccc821dd0ec2`; caffeine `70a2d1891a5feaff5d129280562bb6e01930480a9cf2b7359dea2d47b43db1e0`; density `148111c400254491b5a23baef5935a3c68f76965ed38e468431127e8a7fc96a2`.

Independently reconstructed the 26 recorded requests from the fixture and deterministic `WO-1`–`WO-3` IDs. Their sequence digest is `aab0510e295999dd4baed668d379bbe3ab29ee241c5c86b5cddfeed5f32acae6`. This covers recorded method/path/body hashes and MCP identities; session/login traffic and credential headers are excluded. Concurrent claims are recorded in fixed identity order, not network arrival order.

## Recorded result comparison

| Variant | Fixture/runner/request hashes | Full outcome independently rehashed |
|---|---|---|
| Single host | Match | Yes, `evidence.json → acceptance.outcome` |
| libSQL | Match | Yes, `evidence.json → acceptance.outcome` |
| Replicas | Match | Yes, `acceptance.json → outcome` |
| Blob adapter | Match | Yes, `evidence.json → canonical_outcome`, plus independent disposable rerun |

All produce outcome digest `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67`. All four retained full outcomes and the independent Blob rerun encode to identical canonical JSON bytes. Each records successful recovery verification with the same digest.

Independent arithmetic gives caffeine **24, 45 mg/L** (OLS slope 200, intercept 40) and density **1.08, 0.8 g/mL**. Independently reconstructed batch/control digests match: caffeine `e935c8ca89a1cf817cd997dbf6c6eb576d94f36260a697db220711584d6dc002`; density `2eaaa06a8d2169e0bb14f1661af082bbf19ddb6a1613923c5f40e8403d39b538`.

The failed caffeine revision remains failed (prediction 3,280 versus expected 16), with passing agent-authored tests; corrected revision 2 passes a fresh control at 14.382. Both histories, submission counts, approvals, file digests and checked values survive normalization. Harness assertions also require exact upload bytes, two result values, the top-level unit, receipt provenance and replay equality.

## Material normalization limits

Scratch response-mutation tests against the unchanged `observe()` establish:

| Mutation | Result |
|---|---|
| Flip failed submission to passed; drop a result row; change top-level unit; corrupt upload bytes | Rejected |
| Change unknown sample ID or per-row unit | Accepted; identical outcome hash |
| Remove receipt standards; alter receipt control expected/predicted values while retaining its passed flag | Accepted; identical outcome hash |
| Remove the non-agent blind-control check from submission check evidence | Accepted; identical outcome hash |

These are demonstrated harness blind spots, not observed corruption in a variant. [`observe()`](../acceptance.py) projects result rows to values and omits other receipt fields and most check evidence. Replay equality only compares two responses within that deployment. The recorded batch digest is not recomputed by the harness from receipt rows. JSON key sorting itself is harmless here; selective field omission is the material limit. A claim of complete evidence preservation needs comparison of full normalized receipts/checks, preserving sample identity, per-row units, calibration and control evidence.

## Meaning for simulated versus real data

This establishes parity of the exact simulated protocols, CSVs, controls and submitted programs across the tested storage/process arrangements. Programs are fixed fixtures submitted over MCP; stochastic model generation is outside this comparison. Caffeine begins with already integrated peak areas. Density excludes temperature/buoyancy and physical-instrument validation. Identical simulated inputs and outputs therefore establish a software regression result, without establishing accuracy on real samples, raw-instrument processing, a method's full range or measurement uncertainty.

Verification scripts and the independent Blob state are in `/private/tmp/lf-input-parity-audit/`; its processes and temporary stores were removed. Only this audit file was written in the repository. No unresolved blocker to the bounded input-parity conclusion; the normalization limits block the stronger complete-evidence claim.
