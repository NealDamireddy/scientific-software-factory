# Exploratory agent comparison

This exercise checks whether the review instructions change an agent’s answer on a published non-B12 record. It evaluates the agent-readable skills. The CSV checker separately expects its documented four-column input format.

**Source.** The 30 `weight,group` observations in R’s PlantGrowth dataset, preserving their source order. The [dataset documentation](https://stat.ethz.ch/R-manual/R-devel/library/datasets/html/PlantGrowth.html) describes a control and two treatments. The extracted CSV supplied to the reviewers contains no unit or individual plant identifier.

**Task.** Review the proposed report “The average weight in trt2 was higher than in ctrl. The first treated plant weighed 6.31 g.” Use the supplied record and cite the evidence. Two separate coding-agent sessions received the same observations and question. One received no skill files for this exercise. The second received Data intake and provenance and Claim-to-evidence review. Neither received an expected answer.

**Results.** Both correctly computed 5.526 for trt2 and 5.032 for ctrl (10 observations each). Both flagged the missing unit and distinguished the first trt2 row (6.31) from the first treatment row in file order (4.81, trt1). The skills-assisted answer also cited physical CSV lines 22–31 and 2–11, showed the calculation with sums 55.26 and 50.32, and requested a sample/order key and unit definition.

**Limits.** One comparison using two existing agent sessions, one public dataset, and a constructed claim. There was no independent scientist scoring the answers. Accuracy was tied on the two central questions. Assess generalization with unseen lab records, independent repeated sessions, and researcher scoring of correct findings, false alarms, citations and clarification requests.
