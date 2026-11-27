# Do research decisions follow the lab context?

Six independent coding-agent sessions each saw the same three measurement files, dictionary, illustrative bench observations and method library. Each reviewer saw just one set of investigator requests. For each request set, one reviewer received the three earlier skills from commit `6db8b50` and one received the three revised skills. Every reviewer was asked to read the assigned skills and could compute locally. No reviewer saw the other contexts, answers or rubric. The grader received anonymous answers and the context-to-answer mapping without knowing which skill version each set used.

The standards, chick weights and earthquake observations are the same unfiltered published R records used in the [prior comparison](../independent-record-reviews/SOURCES.md). The supplemental readings, tolerances, manifests, correction policy and analyst notes are constructed lab context. The numbers below describe the evaluation cases.

| Decision | Request J | Request T | Request V |
| --- | --- | --- | --- |
| Report the chemistry result | Signed revision 1. Release 0.6082 mL equivalent. | Signed revision 2. Withhold the result. | Revision field missing. Retain the estimate, seek verified assignment and give conditional release decisions. |
| Describe growth in Diet 1 | Same 16 birds at both endpoints. Mean individual gain 136.19 g. | Populations observed on each day. Change in mean weight 136.35 g across 20 at birth and 16 at follow-up. | All 20 initially enrolled. Four endpoints are missing, so observed mean individual gain for the full cohort is undetermined. |
| Summarize seismic acceleration | Every reading counts equally. Mean 0.15422 g across 182 records. | Every earthquake counts equally. Mean 0.13290 g across 23 event means. | Same earthquake question plus an unsigned station suggestion. Mean stays 0.13290 g. Station attribution remains unconfirmed. |

The decisive chemistry evidence is the same 3.83% absolute error from a reference material kept outside the fitted standards. That passes revision 1's 5% tolerance and fails revision 2's 2% tolerance. A later unsigned recollection leaves both conditional outcomes available. In the earthquake case the unsigned note affects what one might investigate about line 80. Its event ID and acceleration are still documented.

## Outcome

Each version earned 9/9 decision points, 9/9 reasoning points and 6/6 cross-context comparisons. The blind grader found no unsupported claims. The revised skills elicited the intended behavior, including declining to change an unaffected conclusion. This trial did not show an incremental advantage over the earlier instructions. Each version had one reviewer per context, all materials fit in a short packet, and the checks and competing revisions were easy to find. No scientist graded the answers. A harder follow-up would give reviewers an unfamiliar export and a realistic archive of methods and notes, and score whether they retrieve the controlling evidence without being directed to it.

## Reproduce or inspect the comparison

- Read the [shared bench record](shared/bench-record.md), the requests [J](contexts/J.md), [T](contexts/T.md) and [V](contexts/V.md), and the [frozen scoring rules](scoring/rubric.md).
- Compare J's [previous](answers/46.md) and [revised](answers/11.md) answers, T's [previous](answers/27.md) and [revised](answers/53.md) answers, and V's [previous](answers/74.md) and [revised](answers/38.md) answers.
- Run `shasum -c manifest.sha256` and `python3 scoring/verify.py` from this directory to confirm the inputs and recalculate the key. The previous skill snapshot is available in Git at `6db8b50:reference-ui/skills/`. The revised snapshot is in the same commit as this evaluation.
- See the [blind grading](scoring/blind-review.md) for item scores, reasons and cross-context comparisons.
