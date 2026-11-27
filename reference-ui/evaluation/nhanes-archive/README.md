# Can an agent find the governing lab method in a public archive?

The dashboard audit used real CDC NHANES codebooks, released measurement files, laboratory procedure manuals and analytical notices. The reporting request was constructed for this evaluation. The archive spanned seven survey cycles from 2001–02 through 2013–14, with 57 files totaling 20.9 MB: 20 SAS transport files, 20 codebooks, two notices and 15 PDFs totaling 443 pages. The subset includes neighboring releases, other analytes and a legitimately superseded series. Original filenames and cycle directories were preserved. The 57 files are a curated subset of the public archive.

## Task and evidence

Reviewers received the same [investigator request](request.md), complete local archive and local calculation tools. They knew the analyte, cycles, disputed caption and record ID. They had to find the relevant files, follow the codebook-to-manual links, select fields and distinguish what a public release establishes from what would require internal run records. They received no filenames, preselected source excerpts, answer key, or hints about competing method numbers. Web access and peer consultation were excluded by instruction. Skill-assisted reviewers could choose from the complete workspace skill library as published at `d327ee0`. The archive was new to this evaluation series; prior model familiarity with public CDC documentation cannot be excluded.

| Cycle | Applicable release and measurement history | Nonmissing published totals | Unweighted median |
| --- | --- | ---: | ---: |
| 2005–06 | VID_D, LBDVIDMS. Original DiaSorin radioimmunoassay; the comparable released value is a regression-derived LC-MS/MS equivalent. | 8,306 | 56.8 nmol/L |
| 2009–10 | VID_F, LBXVIDMS. Direct LC-MS/MS components; cycle documentation links manual 4027.03. | 8,700 | 62.5 nmol/L |
| 2013–14 | VID_H, LBXVIDMS. Same analytical approach; cycle documentation links manual 4027.06. | 8,437 | 62.4 nmol/L |

The 2013–14 component's broad continuity statement and a changed manual number can both be true. Neither the printed number nor the document creation date establishes the procedure actually used for a particular specimen. The published total for record 73557 is 28.9 nmol/L. Specimen-specific certification requires the as-run procedure record and a specimen-to-batch link with that batch's actual QC result. These medians summarize available release values, without survey weights.

CDC documents distinguish the former RIA-harmonized values from the recommended standardized totals and define which components contribute to total 25-hydroxyvitamin D. [CDC analytical note](https://wwwn.cdc.gov/nchs/nhanes/VitaminD/AnalyticalNote.aspx), [2009–10 method](https://wwwn.cdc.gov/nchs/data/nhanes/public/2009/labmethods/VID_F_met_vitamin_D.pdf), [2013–14 codebook](https://wwwn.cdc.gov/nchs/data/Nhanes/Public/2013/DataFiles/VID_H.htm) and [2013–14 method](https://wwwn.cdc.gov/nchs/data/nhanes/public/2013/labmethods/VID_H_MET.pdf).

## Outcome

| Measure | With workspace skills | Without workspace skills |
| --- | ---: | ---: |
| Correct audit findings across two independent reviews | 20/20 | 20/20 |
| Found both cycle-specific method manuals | 2/2 | 2/2 |
| Correctly limited specimen-level certification | 2/2 | 2/2 |

A separate reviewer graded the anonymous reports against the [ten-item rubric](scoring/rubric.md) fixed before dispatch. No substantive numerical or citation errors were found. All four reproduction scripts ran successfully on a second download of the archive. Read the [blind scores](scoring/blind-review.md), [skill-assisted report 18](answers/18.md), [skill-assisted report 52](answers/52.md), [ordinary report 36](answers/36.md) and [ordinary report 79](answers/79.md).

One extra finding illustrates the potential value of going beyond a manual's title page. Reviewer 18 followed §7 of the 2013–14 manual to its explicit account of a change in calibration practice in 2013. This supports a particular difference between the methods documented in the archive, although it cannot establish the exact procedure for the individual specimen. The other three reports established the revision distinction without identifying this detail. It was outside the frozen rubric and is a single observation.

The result supports autonomous evidence retrieval for this release audit. Both groups reached the scoring ceiling. This experiment does not establish an accuracy advantage from the skills or validate retrieval across private lab systems.

## Skill selection and scope

The two skill-assisted reviewers independently chose Data intake and provenance. Reviewer 18 also used Method comparison and Evidence summary. Reviewer 52 used Method reference and Instrument record. Neither reported loading Calibration review or Claim-to-evidence review. The observed behavior therefore tests navigation with the published library available, rather than the incremental effect of any single playbook. Both other reviewers had the same archive and local tools with no workspace skills.

The agents searched an already accessible file tree using native archive names and codebook links. This test does not exercise the application's live connectors, permissions or remote document indexing. No hidden archive log, instrument audit trail or independent scientist adjudication was part of the evidence.

## Reproducing the audit

The [source manifest](sources.csv) records official URLs, byte lengths and SHA-256 digests. The repository contains the evaluation materials and references to CDC-hosted data. To restore and verify the archive on a machine with Python 3 and R with the foreign package:

```sh
python3 restore.py /tmp/nhanes-archive
Rscript --vanilla verify.R /tmp/nhanes-archive
```

The restorer checks all files against the frozen manifest. For the two live CDC notices, it also accepts identical HTML after stripping only the rotating hidden ASP.NET VIEWSTATE value. All other bytes must match. A fresh download was verified using these checks. The numeric verifier reads the original SAS transport files, checks unique identifiers, and recalculates counts and unweighted medians.
