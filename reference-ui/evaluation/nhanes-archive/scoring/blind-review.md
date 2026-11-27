# Blind review of four NHANES release audits

Each answer earned **10/10** on the frozen rubric. I checked the four answers by numeric ID against the same request, rubric and archive. The answers tied on all three requested retrieval measures.

## Per-item scores

| Frozen rubric item | 18 | 36 | 52 | 79 |
|---|---:|---:|---:|---:|
| 1. Standardized 2005–06 release, original DiaSorin RIA and predicted equivalent | 1 | 1 | 1 | 1 |
| 2. Archived RIA alternative, 2015 guidance and use of the already standardized field | 1 | 1 | 1 | 1 |
| 3. 2009–10 codebook link, manual 4027.03 and direct LC-MS/MS | 1 | 1 | 1 | 1 |
| 4. 2013–14 codebook link, manual 4027.06 and reconciliation with the continuity statement | 1 | 1 | 1 | 1 |
| 5. 2005–06 count 8,306 and median 56.8 nmol/L | 1 | 1 | 1 | 1 |
| 6. 2009–10 LBXVIDMS, count 8,700 and median 62.5 nmol/L | 1 | 1 | 1 | 1 |
| 7. 2013–14 LBXVIDMS, count 8,437 and median 62.4 nmol/L | 1 | 1 | 1 | 1 |
| 8. VID_H, SEQN 73557, LBXVIDMS 28.9 nmol/L | 1 | 1 | 1 | 1 |
| 9. Withhold specimen revision certification and identify the needed run evidence | 1 | 1 | 1 | 1 |
| 10. Withhold batch-QC certification and identify the missing linkage and actual QC evidence | 1 | 1 | 1 | 1 |
| **Total** | **10** | **10** | **10** | **10** |

## Retrieval measures

| Measure | 18 | 36 | 52 | 79 | Total |
|---|---:|---:|---:|---:|---:|
| Found governing 2009–10 manual | 1 | 1 | 1 | 1 | 4/4 |
| Found governing 2013–14 manual | 1 | 1 | 1 | 1 | 4/4 |
| Distinguished cycle documentation from specimen evidence | 1 | 1 | 1 | 1 | 4/4 |

## Evidence checked

- The October 2015 advisory in `notices/AnalyticalNote.htm` replaces the November 2010 advice, recommends using the standardized historical release and gives the 2005–06 regression on original RIA. The old notice lists both `VIDRIA_D` files. In the 2005 manual the cover identifies the DiaSorin assay, while the release table labels `LBDVIDMS` “Vitamin D LCMSMS (nmol/L).”
- The Laboratory Method Files links in `2009/VID_F.htm` and `2013/VID_H.htm` resolve by year and basename to `2009/methods/VID_F_met_vitamin_D.pdf` and `2013/methods/VID_H_MET.pdf`. In each PDF, physical page 1 gives the method number and creation date, and page 2 identifies the cycle, lab file and total. The 2013 codebook says there were no changes to method, equipment or site in that cycle. Its Analytic Notes explicitly address comparison with data collected since 2007.
- Independent reads of the transport files with R `foreign::read.xport` reproduced 9,440/8,306/56.8, 9,835/8,700/62.5 and 9,422/8,437/62.4 (rows/nonmissing/median in nmol/L). The HTML frequency tables corroborate the counts. The alternative `VIDRIA_D:LBDVID` has 8,306 nonmissing and a median of 22 ng/mL. The first and only `VID_H` row for SEQN 73557 has total 28.9, D2 1.45, D3 27.5 and epimer 1.16, with flags 0, 1, 0 and 1 respectively. No run or batch ID appears in the released columns.
- The 2013 manual §3 describes the batch file, acquisition information and LIMS approval. Sections 10 and 18 describe controls and specimen tracking. Section 19 starts on printed page 25. Its three QC lot summaries and charts appear on printed pages 26–28 (physical PDF pages 27–29). They provide no link to respondent 73557.

## Selective attention and reproducibility

- **18** checked the 2007 and 2011 neighboring manual covers and found 4027.03 in both. Its extra calibration finding is supported. Section 7 of the 2009 manual (PDF page 11) specifies 4% albumin in PBS. Section 7 of the 2013 manual (printed page 13) records the 2013 introduction and comparable performance of solvent-based calibration using 70% methanol/water. The audit does not assign an exact switch date or calibration to the individual specimen.
- **36** cross-checked the 2011 manual, the explicit “since 2007” recommendation, frequency tables and the 2013 specimen-tracking section. Its reported missing counts also reproduce.
- **52** checked whether two unrelated analyte files also contained the survey participant key. Both `2013/FOLATE_H.xpt` and `2013/TST_H.xpt` do. Its use of the named vitamin D release and analyte correctly disambiguates the record.
- **79** traced the 2005 test principle to §1, which does identify an equilibrium RIA, and explicitly checked uniqueness for SEQN 73557 in its code.

I executed the R blocks from all four reports with the archive as working directory. Each reproduced the three primary rows of summary statistics and the target record. The differing examples of incidental evidence do not produce any separation under the fixed rubric.

## Deductions and incidental errors

There were no rubric deductions and I found no independently contradicted incidental factual claims or erroneous report citations. The two later method numbers are on the manual covers. Their applicability is corroborated by the immediately following release tables. The QC page references use printed numbering and agree with the underlying PDF pages. These results describe performance on this audit alone.
