# Cross-system specimen release audit

Eight independent reviewers audited four fictional environmental water specimens at two historical cutoffs. Everyone received the same three source exports. No complete specimen-to-release chain was present in any one system. The study measures whether agents can assemble and challenge that chain once they have read access. The notebook and registry are exported records and the instrument archive is a SQLite database. No live lab connection was exercised.

| Source | Relevant records |
| --- | --- |
| Lab notebook | Accessions, signed physical transfers, unresolved custody exceptions, report receipts and a signed amendment to an earlier release selection |
| Instrument archive | 54 acquisitions, 11 control events and 6 batch dispositions. Batch identifiers can recur on different instruments. Control events retain the time they were posted and whether they were signed. |
| Method registry | Four controlled revisions, instrument-specific deployment intervals, control material certificates and signed or proposed variations from a standard limit |

## Findings

| Identical question within each pair of groups | Release decisions, without skills | Release decisions, with skills | Evidence checks, without skills | Evidence checks, with skills |
| --- | ---: | ---: | ---: | ---: |
| Detailed audit | 16/16 | 16/16 | 23/24 | 24/24 |
| Short shift handoff | 16/16 | 16/16 | 24/24 | 24/24 |

Each group in each row had two reviewers. All 64 specimen-by-cutoff verdicts were correct, with no unsupported positive release or undue hold. A single evidence point distinguished the detailed reports. One control reviewer correctly described the notebook's expected routing and held the specimen, but did not explicitly say that the routing note was unsigned. This omission affects how easily the next shift can defend the decision. It did not change the verdict.

The earlier benchmark's high baseline persisted for release accuracy after adding a revision boundary, a signed exception, serial-specific batch collisions, mixed units, timestamped corrections and a broken physical link. Even with a short handoff, this agent could follow the simulated lab's documented rules. The result supports using the cases for regression testing. It gives little evidence of a decision-quality improvement from the skills. To discriminate between skill versions, use held-out cases selected by a lab supervisor for their operational significance and have the supervisor grade the evidence and decisions without knowing the condition. Keep this rubric and these results fixed.

## Expected release decisions

| Specimen | April 17 at 00:15 UTC | April 17 at 18:00 UTC | Decisive evidence |
| --- | --- | --- | --- |
| BW-731 | Release | Release | The signed amendment selects the repeat, AQ-509. The registered variation allows a high-control error of exactly 1.50%. The earlier acquisition reported the same reading from a rejected batch. |
| BW-744 | Withhold | Release | For AQ-512, the early signed high control has 2.003% error against an inclusive 2.00% limit. The batch's signed acceptance conflicts with that result. A later signed correction yields 1.98% and a new batch acceptance. |
| BW-752 | Batch control unverified | Same | AQ-518 belongs to CX-09. A different instrument reused the same batch identifier. CX-09's high control is unsigned, even though its numerical value is within limits and the batch disposition says accepted. |
| BW-760 | Specimen identity unresolved | Same | Receipt EX-60 selects AQ-526, and that run's controls pass. Two specimen accessions could occupy its well. The alternate well reports the same reading, and the notebook contains no signed physical assignment. |

## Comparison design

The primary comparison used the same [detailed audit question](request.md) for two fresh reviewers with the eleven published research skills available and two reviewers using ordinary reasoning. An exploratory comparison used a shorter [shift question](shift-request.md) with two new reviewers per condition. All eight had native file access, local computation and no peer answers or external research. Skill-assisted reviewers selected their own skills from the catalog in commit `52c026d`. No tools or evidence were taken away from the controls apart from the workspace skills.

The detailed-question answer IDs are 31 and 84 without skills, and 47 and 62 with skills. The shift-question IDs are 12 and 26 without skills, and 58 and 93 with skills. All four assisted reviewers consulted Data intake and provenance, Instrument record, Method adherence and Calibration review.

The [rubric](scoring/rubric.md) was fixed before primary dispatch. It separately scores eight operational decisions and twelve evidence checks. The shift wording was frozen before those sessions started, after one primary reviewer returned and before primary grading. Skill conditions were withheld from the grader. See the [design record](design.md), the [blind grade](scoring/blind-review.md) and the [original responses](answers/).

## Reproduce the evidence

The frozen exports are in [inputs](inputs/). An independent verifier uses the receipt ledger, signed custody entries, instrument and batch keys, UTC timestamps, active deployments, signed exceptions, lot-specific targets, and decimal arithmetic. Run the following commands from this directory.

```sh
shasum -c inputs.sha256
python3 verify.py inputs
```

The signatures in these fictional exports are record attributes. The exercise measures how a reviewer uses their documented authority. It does not verify cryptographic signatures or access control. No private or production lab records were used.
