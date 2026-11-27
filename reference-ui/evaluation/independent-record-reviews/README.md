# Independent reviews of three research records

The experiment compares coding-agent reviews with and without the 11 portable research skills at commit `49ea8fc`. Four fresh reviewers each examined all three complete CSV files. Two reviewed with ordinary reasoning and calculation tools (K, R). Two could also choose any of the eleven skills (M, P). The reviewers saw the same assignment, dictionary, records and 180-word allowance per case, with no answer key, peer answers or outside research. No reviewer worked in both conditions. Every draft claim was constructed for this exercise.

The 12 binary scoring items and one traceability item per case were fixed before dispatch. The lead computed a key from R and independently recomputed it in Python. A fifth agent received anonymous responses, records and the fixed rubric without condition labels. The source materials and the verbatim answers are included below.

- [Published dataset sources and regeneration instructions](SOURCES.md)
- [Assignment](packet/assignment.md) and [dictionary](packet/dictionary.md)
- [Frozen rubric](scoring/rubric.md), [numeric verification](scoring/verify.py) and [blind grading](scoring/blind-review.md)
- Ordinary reviews [K](answers/K.md) and [R](answers/R.md)
- Skills-assisted reviews [M](answers/M.md) and [P](answers/P.md)

## What changed with access to skills

| Result | Ordinary reasoning (K, R) | With skills (M, P) |
| --- | ---: | ---: |
| Required findings stated, two reviews × 12 checks | 20/24 | 22/24 |
| Case reviews with a reproducible locator or calculation | 6/6 | 6/6 |
| Case reviews with an explicit CSV line or line range | 1/6 | 6/6 |
| New substantive factual errors found by grader | 0 | 0 |

All four reviewers made the same release decisions. Both assisted reviewers identified all 16 earthquake records with missing station IDs by physical line. One ordinary reviewer cited one example, and the other supplied the missing count. Some assisted citations span a whole dataset or group, so this count measures presence of line citations, not their specificity. All reviewers correctly computed the paired weight change and event-weighted mean. One ordinary reviewer left the subtraction implicit and did not explicitly explain the continued usability of records with missing station IDs. Accepting its implicit subtraction gives 21/24 for ordinary review. The two-point difference therefore concerns completeness of explanation more than discovery of scientific errors.

| Case | Finding all four reached | Boundary or omission |
| --- | --- | --- |
| Formaldehyde | The six-point line fits closely (R² = 0.99905). A proposed response of 0.800 exceeds the highest standard (0.782), and the fitted quantity is in mL. | All withheld the result. None named an independent way to establish method accuracy. |
| ChickWeight | Of 20 chicks at baseline, 16 had the endpoint. Their paired mean gain was 136.19 g. The two changing cohorts give a difference of 136.35 g. | All got the paired calculation. One ordinary reviewer supplied the inputs and left the marginal subtraction implicit. |
| attenu | Averaging 182 readings gives 0.1542 g. Averaging the 23 earthquake means gives 0.1329 g. | All counted 16 missing station IDs. Both assisted reviewers linked every affected row and explained why its event-level evidence survives. |

## Which skills were exercised

Both assisted reviewers selected **Calibration review**, **Claim-to-evidence review** and **Data intake and provenance** for the standards. They selected the latter two for the chick and earthquake cases. Both also consulted **Repeat comparison** and judged that a scheduled follow-up falls outside its scope of an authorized rerun. The other seven skills had no reported use. This measures agent interpretation of native records. The workspace's four-column CSV checker was outside this evaluation.

## What to improve

1. **Calibration review.** Give the agent a specific check for a validation claim. After establishing the observed interval, ask for a check standard independent of those used to fit the curve, its expected and observed response, and the method's acceptance rule. A dilution or an extended curve can address the sample's range. The validation claim still requires its own evidence. Test with a high-R² curve whose independent check fails.
2. **Claim-to-evidence review.** For a statement about change, specify the subject ID, endpoints, and matched denominator. For a statement about a group average, name what gets one vote and calculate using that unit. Test on a record where changing denominators or weighting reverses the conclusion. The present reviewers solved both cases, so these are instructions to preserve that behavior on harder records.
3. **Data intake and provenance.** Ask which claims survive a missing identifier and link the affected rows. A missing station prevents station attribution while leaving that reading usable for a calculation grouped by its recorded earthquake. Test a record with both missing station IDs and missing event IDs so the reviewer must distinguish the consequences.

Separate future cases would be needed to assess run approval, instrument identity, method revisions and dilution reconstruction. Two responses per condition on three public, well-known datasets offer limited evidence about performance on unseen laboratory exports. The grading is agent-based. No scientist adjudicated the release decisions.

## What belongs in the lab skills

The examples test a shared reasoning process. The agent needs the question and decision the scientist is considering, the applicable method and its revision, how the samples or events relate, the original records, and which decisions belong to the researcher. Each is context to retrieve when relevant. A missing instrument record, for instance, can matter to a calibration decision without preventing a descriptive count of the supplied observations.

A portable instruction to put in front of the reviewer:

> State the claim in terms that distinguish plausible interpretations. Identify what was actually observed, what was derived, and which assumptions connect the two. Look up the applicable method, definition or acceptance criterion in the supplied lab records. Ask what evidence could change the conclusion and whether that evidence is independent of the evidence already used. Report the conclusion that survives, its scope, and the smallest missing fact that would change the decision. When plausible interpretations produce materially different answers, show the alternatives and identify which choice requires scientific judgment.

A stronger holdout would give an agent the same measurements with different scientific questions or different documented method revisions. Equal weight per earthquake and equal weight per station reading both answer legitimate questions. A good reviewer selects or explains the weighting that matches the stated question. If the question leaves the target unresolved, a conditional answer or a focused clarification is appropriate. A subsequent lab pilot should include raw exports, method revisions, analyst notes, conflicting evidence and a domain expert judging the reasons given.
