# Does stating the scope of certification improve a release review?

Across three public lab archives, every reviewer identified the property covered by the issuing source and the status of the disputed value. All 18 corrected the proposed lab entry and avoided the consequential overclaims defined for their case. Both blind graders awarded identical scores. This pilot shows the revised skill handles all three cases, but gives no evidence of an accuracy gain over the previous version.

| Records supplied | No skill | Previous claim-to-evidence | Revised claim-to-evidence |
| --- | ---: | ---: | ---: |
| NIST Portland cement clinker certificate and characterization report | 9/10 | 10/10 | 10/10 |
| IAEA caffeine reference sheet and an isotope laboratory study | 10/10 | 10/10 | 10/10 |
| USGS water laboratory intercomparison report | 10/10 | 10/10 | 10/10 |
| **All criteria** | **29/30** | **30/30** | **30/30** |
| Two source-coverage and value-status criteria per review | 12/12 | 12/12 | 12/12 |
| Consequential overclaims | 0/6 | 0/6 | 0/6 |

In the clinker case, one baseline reviewer correctly distinguished the 3.31% certified periclase phase fraction from the 4.37% informational bulk MgO value. The omitted point concerned where the earlier conflicting statement appeared: the reviewer identified the earlier report and omitted its abstract as the locator. [Answer 256](trial/answers/material/256.md) · [NIST sources](cases/material/sources.md)

For caffeine, reviewers distinguished the carbon isotope reference value for calibration from the oxygen information value for quality control. They also separated the issuer's uncertainty from the interval reported in a separate laboratory paper. In the water comparison, reviewers identified the chloride consensus value, the spread of participants’ results and the distinct criterion used to rate the lab. They avoided inferring a certified concentration from that report. [IAEA sources](cases/isotope/sources.md) · [USGS sources](cases/interlab/sources.md)

## Design and limits

The single revised instruction asks the reviewer to identify the issuer, material or lot, exact property, value, units, uncertainty and consequential conditions in the text they would release. It also asks them to preserve the issuer’s status for every disputed value, and to name the evidence needed when the available record only reports measurements. The skill’s selection description was broadened to cover certification claims. Reviewers were explicitly given the skill in both treatment conditions, so this trial measures reasoning after delivery.

Each archive supplied an illustrative decision question and labelled records transcribed or summarized from primary public publications. These archives were new to this evaluation series. The rubric, questions, records and skill snapshots were frozen before dispatch. Two independent sessions per condition and archive received identical question text and records. The empty-list arm used the same no-skill prompt and tool-free launcher as the earlier bilirubin trial. Scores came from fresh reviews of these three archives. All 18 sessions ran gpt-6.2-sol through Codex CLI 0.167.0. Two further graders independently scored anonymous answers before seeing the condition assignments.

There were three distinct cases. Repeating a case twice does not add a new archive. Every arm reached the ceiling for the targeted distinctions. The packets put the relevant source material within reach and the questions disputed particular entries. Live search, private records, and spontaneous discovery of a certification issue in open-ended lab work remain untested. Both graders were models. Their agreement cannot substitute for adjudication by a lab scientist.

[Protocol](protocol.md) · [Previous and revised skill text](versions/) · [Verbatim answers](trial/answers/) · [Condition, version and model records](trial/conditions.json) · [Grader A](scoring/grader-a.md) · [Grader B](scoring/grader-b.md)

To verify the frozen inputs and recompute the totals, run `shasum -c frozen.sha256` and `python3 summarize.py` from this folder. To repeat the model calls using the frozen skill versions, run `python3 run_trial.py /path/to/new-results` with a signed-in Codex CLI and Python 3.11+. The output directory must be new.
