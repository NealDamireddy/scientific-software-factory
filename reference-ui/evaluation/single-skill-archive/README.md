# Single-skill review of the NIST bilirubin archive

The editor had to decide whether a proposed catalogue entry confused certified bilirubin purity with elemental survey estimates. The reference-material certificate and NIST laboratory report are real. The editorial request was constructed for this evaluation. It uses a compact selection of records new to this repository’s evaluation series. The source report itself contains conflicting accounts of which elements failed an instrument’s quality check. [Request](question.md) · [Source records and original NIST publications](sources.md)

## Findings

| Instructions delivered | First blind grader, by block | Second blind grader, by block | Identified both method-specific controls |
| --- | --- | --- | --- |
| Baseline, empty skill list | 7/8, 6/8 | 7/8, 6/8 | 0/2 |
| Data intake and provenance | 8/8, 7/8 | 7/8, 7/8 | 2/2 |
| Claim-to-evidence review | 7/8, 8/8 | 7/8, 8/8 | 2/2 |
| Evidence summary | 8/8, 7/8 | 8/8, 7/8 | 2/2 |

All eight reviewers corrected the entry and recognized the conflict between the report’s tables and prose. Both graders recorded zero unsafe overclaims. All six single-skill answers distinguished the water control used for ICP-MS from the oyster-tissue control used for WDXRF, by material name or identifier. The two baseline answers gave the right numerical control scores, but each omitted at least one control’s identity. Both groups understood the measurement. The difference affected how easily a colleague could trace it back to its control.

One baseline, one provenance and one claim-to-evidence answer described the elemental numbers as survey estimates while leaving their uncertified status implicit. One evidence-summary answer omitted an explicit conversion of the elemental total to mass percent. The two graders differed on one more conversion. Answer 537 gave 5640 mg/kg as about 0.6%. The first judge accepted the rounding and the second required the rubric’s 0.56–0.57% precision. Both grades are retained. [First grading notes](scoring/blind-notes.md) · [Second grading notes](scoring/independent-notes.md)

The most promising revision to test is a prompt to **name the material, method and authority for each value the researcher will publish**. In this case that means distinguishing the material being sold, the material used as a control, and the measurements covered by the certificate. A separate reporting check could ask for an explicit unit conversion when using one measured quantity to corroborate another. These are candidates for future testing. Two reviews per condition on a single archive cannot rank the skills or establish a general improvement in release decisions.

## Study design

The [four record files](records/), question, [eight-item rubric](scoring/rubric.md) and source manifest were hashed before dispatch. Two blocks each contained one baseline and one trial for each individual skill. Each answer came from a fresh, tool-free, read-only Codex CLI worker. A fixed seed shuffled order within blocks and assigned anonymous labels. All eight sessions used gpt-6.2-sol and Codex CLI 0.167.0. Each received the same filename-labeled records, question, response format and shared instructions. The only prompt difference between conditions was the enabled skill list. Each treatment used the actual UI catalogue text and the same SHA-256 pinning routine used in experiment delivery.

Two independent graders saw the anonymized answers, records and frozen rubric. Neither received the condition mapping when scoring. The comparison uses the submitted answers, including close calls. No human scientist adjudicated them. The agents received the selected records directly. This measures interpretation of supplied records and leaves performance on live connector retrieval open. Prior model exposure to public NIST records is unknown. [Version and model records](trial/conditions.json) · [Verbatim answers](trial/answers/) · [First grades](scoring/grades.csv) · [Second grades](scoring/independent-grades.csv)

To verify the evidence, run `shasum -c frozen.sha256` in this directory. To repeat the trial with fresh model calls, use `python3 run_trial.py /path/to/new-results` with Node.js 22.6+, Python 3.11+ and a signed-in Codex CLI. The output directory must be new. Model responses can vary across repetitions.
