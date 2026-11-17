# WO-28 review log

## Round 1

Reviewed d59d8e6..d9e6924 with separate read-only delegates for the public contract and SQLite adapter. All 15 catalog tests passed. The domain delegate approved lab-scoped authorization, immutable pins, separate action grants and the curation boundary. The storage delegate reproduced a blocking SQLite data-safety issue. An explicit hidden rowid in INSERT OR REPLACE could evict a revision without colliding with its declared keys.

**Verdict** CHANGES_REQUESTED.

## Round 2

Both delegates reviewed d59d8e6..7227792. The two append-only tables now use WITHOUT ROWID. SQLite rejects both explicit rowid replacement reproductions. The fixed Python 3.13 catalog suite passed all 15 tests.

| Acceptance | Evidence |
| --- | --- |
| CAT-001.7–8 | Read, exact ID lookup, history, proposal, evidence and receipt operations require the owning lab and action before accessing storage. Tests exercise revoked callers, foreign labs, unknown records and identical stream names in two labs. |
| CAT-002.1, .4–5 | Agent and human proposals begin as drafts. Canonical digests, immutable IDs, trusted author, creation time and predecessor survive reopen. Two racing writers at revision zero and at an existing head produce one new revision and one conflict. |
| CAT-003.1, .4–6 | Human-only receipt writes bind the exact lab, model stream, revision, ID and digest. Competing approvers preserve one receipt. A manual reopen yielded revision 1 approved by reviewer and revision 2 in draft. The exact source citation resolved to §4.2, p. 19. The portable suite also approves the successor and restores both decisions and the earlier profile pin. |
| CAT-004.1–2, .6–7 | Separate evidence streams preserve all independent test fields, recording actor and corrections. Tests reject missing fields, invalid origins, unauthorized writers and stale corrections. |

SQLite migration tests cover both context/catalog initialization orders, domain-local schema version checks and rollback of a partially executed migration. An exploratory eight-writer startup race preserved a foreign table, its data and global user_version 37. SQLite integrity_check returned ok. The hosted adapter can reuse all policy and 11 behavioral tests via the scoped transaction and revision-ID lookup hooks.

The curation service validates scientific eligibility before submitting a receipt. Catalog records supply no installed-device authorization. This WO changes no UI, CLI, hosted wiring or shared database objects. Both delegates returned **APPROVED** with zero remaining findings.

Final verification on 7227792 used the locked Python 3.13 environment. The command `python -m unittest discover -s tests -v` passed all 280 tests in 85.030 seconds, including the 15 catalog tests. The change passed `git diff --check`.

**Verdict** APPROVED.

## Published PR review

The coordinator reproduced the reported receipt-write issue in PR #22. A human with approval permission could create a receipt for a revision whose stored evidence gaps were still open. The shared transaction now checks those recorded gaps before inserting a new receipt and returns the gaps to the authorized approver. Scientific assessment of evidence remains with the curation service. A new shared contract test checks refusal, readback of the original draft after reopening, and approval of a corrected successor. The test failed before the change and all 16 SQLite catalog tests passed afterward.
