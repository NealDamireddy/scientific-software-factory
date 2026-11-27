# Historical environmental lab release disputes

Four publicly documented questions and requests about releasing, correcting or qualifying measurement data were replayed using decision-time evidence. The review packets omit personal names, email addresses, institution identifiers and live source links. The underlying samples are environmental, with no human subject information.

| Case | Actual question or request | What the later record establishes |
| --- | --- | --- |
| A · Nitrite | How should the archive resolve three deep-water results above 2.5 when the correction history and apparent quality flags disagree? | The processor restored 0.01 for those three bottles and traced the regression to a later resubmission. |
| B · Tritium | Could three measurements recorded near 195 dbar belong to shallower bottles? | The investigator supplied comparison sections and confirmed a genuine subsurface feature. The archive retained the depths. |
| C · Bottle-file QC flags | Could the originator track down conflicting oxygen and salinity flags and provide a corrected file? | A corrected table arrived. The owner withdrew an initial blanket fix, and later checks still found discrepancies. |
| D · Groundwater volatiles | Make the report and the validation memo consistent about qualifiers for samples whose acidification was disputed. | Investigation recovered some records. Revised forms retained estimated qualifiers for aromatic analytes in affected runs where the laboratory could not verify pH. |

The [packets](packets/) preserve a short original decision request for each case, with contemporaneous facts transcribed or summarized. Case D is a regulator's written instruction. The prose in the table above summarizes the disputes. The [sources and cutoffs](sources.md) identify the original records, their dates and the selection boundaries. The [withheld historical key](historical-key.md) records what happened subsequently. A reviewer could reasonably withhold a decision or leave the mechanism open even where the historical lab later settled it.

## Primary findings

| Condition | Reviewers | Correct decisions as of cutoff | Evidence checks |
| --- | ---: | ---: | ---: |
| Ordinary reasoning | 3 | 12/12 | 24/24 |
| Read the three skills | 3 | 12/12 | 24/24 |
| Optional access, no skills consulted (exploratory) | 2 | 8/8 | 16/16 |

Both independent graders returned the same scores. Neither identified an unsupported definitive change. This experiment did not demonstrate a gain in decision accuracy or evidentiary sufficiency from these three playbooks. The 12 judgments per primary arm come from three reviewers repeating the same four disputes; they are not 12 independent incidents.

The most important retrospective distinctions are in B and D. All reviewers kept the reported depths provisionally; they did not need to know the mechanism the tritium expert established the next day. In the regulatory case, maintaining the disputed qualifiers pending lab confirmation was defensible before the investigation. Predicting the exact set of aromatic compounds or runs covered by the later amended forms was never a scoring requirement.

## Exploratory comparison of the investigator's next action

After the primary ceiling result, two additional blind judges compared 12 pairs, each matched on question and presentation order. Answer identity was removed, left/right position was shuffled and balanced, and a tie was allowed whenever both answers led to equivalent action. This comparison was added after scoring; it is not a second confirmatory endpoint.

| Result agreed by both judges | Pairs out of 12 |
| --- | ---: |
| Skill-assisted answer more actionable | 3 |
| Baseline answer more actionable | 1 |
| Tie | 6 |
| Judges disagreed | 2 |

All three unanimous skill preferences came from **one dispute, C**, with three different reviewers per arm. The skilled answers identified the bottle-linked instrument data and flags needed to verify CTDSAL and CTDOXY. They explained what the contemporary water-sample spreadsheet could establish and the limits of the separately checked instrument profile files. That points the investigator to the right record owner and the right keys before changing a flag. The baseline answers reached the same correct decision and also sought verification, but those three matched answers were less precise about the source for the disputed instrument fields. Compare [assisted answer 34](answers/34.md) with [baseline answer 21](answers/21.md), case C.

For nitrite, both judges preferred one baseline answer because it explicitly verifies the corrected *distributed* file and gives the investigator its version. No pair for groundwater or tritium produced a unanimous skill preference. The positive signal is specific to cross-source verification in this small study and concerns handoff usefulness. It cannot be attributed to a single skill or generalized to other labs.

See the [preference rule](scoring/preference-rule.md), [pair mapping](scoring/pairs.csv), and [first](scoring/preference1.csv) and [second](scoring/preference2.csv) judges' reasons. Run `python3 scoring/summarize.py` to recompute the primary and exploratory results. Run `shasum -c frozen.sha256` to verify the case packets, original rubric and held-out key.

## Study records

Read the [protocol](protocol.md), [frozen rubric](scoring/rubric.md), [reviewers' answers](answers/), and the independent grading notes. Each group had identical evidence and a 145-word limit per case. Orders were balanced across the three baseline and three applied-skill sessions. The packet hashes, key and rubric were frozen before review. The two graders saw neither group labels nor recorded outcomes.

| Order | Without skills | Required skill reading |
| --- | --- | --- |
| A, B, C, D | 21 | 34 |
| C, D, A, B | 68 | 79 |
| D, B, A, C | 87 | 15 |

The applied group read the portable Data intake and provenance, Claim-to-evidence review and Evidence summary playbooks available on branch `codex/research-ui` at `b854a70`. In a separate optional-access check, reviewers 43 and 56 independently reported that they did not consult any playbook.

These were public archive or regulatory measurement-report disputes. They are not four confidential internal specimen authorizations. The packets preserve evidence present by the cutoff rather than every file a lab might have possessed. The small, nonrandom selection, shared model family, curated packets and possible recognition of public cases limit inference. The retrospective dispositions validate the case histories. They neither reveal what the reviewers actually remembered nor replace scientific adjudication of a close call.
