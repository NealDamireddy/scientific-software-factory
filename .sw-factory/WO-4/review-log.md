# Independent review and verification

Independent clean Chrome review approved. Fresh PI request 667acd4d2ee848fc893e6f60b955b72e and approved child 0dfb62380d1942a2a144bd81bf7d6df3 completed through reveal and replay in 43.767 seconds. Estimate 29.98624 mg/L, sealed preparation 30 mg/L. During generation the previous-run view opened and returned to the same live task. The static archive navigated from the original EPR page, verified both releases and reproduced its original 32.00683 mg/L estimate. Production build passed. Python suite 29/29. Chrome passed at mobile and desktop widths.

Verdict: APPROVED

## Presenter laptop rehearsal on November 14, 2026

Clean Chrome on macOS, simulated 550 nm instrument, separate initially empty live store. The final run took 38.075 seconds from PI submission through reveal, replay and evidence export. The archived run opened during generation and returning restored the same active ID.

| Release | Fresh task | Generated source revision | Independent checks |
| --- | --- | --- | --- |
| Direct v1 | 313504c6598b4d0790f9cc44d67541e7 | 483e95c7422c945a393d15993e5c54b8a792719aec92ec942411fcc19f5a6b52 | 5 passed |
| Prepared v2 | a3ef947a0c194a9ea4b6aea7a23f50cf | 76e37ecc26e5d6f515e31ee4186695502020ef0b4664783b0dc3c7d3291bc3a0 | 16 passed |

Preparation was recorded during v2 generation. Premature reveal was rejected. The host saved 35.03518790890618 mg/L before revealing 35 mg/L. Both runs matched on a separate offline replay of the downloaded package. A separate Chrome session confirmed the archive-only controls and the downloaded archive matched the original. All seven readiness checks, all 52 tests and the production build passed.

Independent review approved the restart and archive-only changes. The reviewer ran 21 targeted tests and independently checked an occupied port, immediate restart, overlapping task IDs and an absent store. The fallback can run alongside an active presenter without writing to its store.
