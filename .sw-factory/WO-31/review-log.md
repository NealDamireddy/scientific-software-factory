# WO-31 review log

## Round 1

Two delegates reviewed the eight paths changed from the merge base with origin/main through 3f1fafb. One reviewed the domain and adapter. The other reviewed the behavioral fixture, SQLite tests and execution records.

- **Requirements and blueprints.** Both approved. The records retain scientific provenance, exact ordered pins, scope, author, predecessor, questions and limitations. Each new specification reads as draft. Receipts bind human decisions to current specification pins and survive a reopen.
- **Architecture.** The protocol exposes all six operations and the action names. SQLScientificArtifactRepository implements them. A hosted adapter can provide its own transaction executor and migrations. SQLite uses only domain-prefixed objects and a private migration version.
- **Security and data safety.** A trusted principal checks every call. Foreign-project references fail before lookup, receipt actors come from the principal, and a single transaction covers pin lookup, expected-revision comparison, insertions and reconciliation. Both SQLite migration orders preserve the existing context store.
- **Tests.** Both delegates independently ran the scoped suite. The domain delegate also tried 30 competing decision/edit transactions. Both lock orderings occurred, and all successor specifications retained draft state. The test delegate confirmed that the fixture accepts a repository factory and runs without SQLite dependencies.
- **Exploratory check.** A Python caller saved a protocol and pinned specification, rejected revision 1, reopened a temporary database and inspected the rejected state, unchanged protocol pin, UTC decision time, actor, rationale and limitations.
- **Advisories addressed.** The fixture now revises knowledge evidence, reopens both versions and verifies historical requirement pins. The adapter rejects malformed limitation containers, and the fixture verifies failed decisions leave no receipt.
- **Verification.** Python 3.13.16 with the locked jsonschema 4.26.0 passed all six tests in `python -m unittest -v tests.test_scientific_artifact_repository`. The full `python -m unittest discover -s tests -v` suite passed all 271 tests in 84.461 seconds. `git diff --check` passed.

**Verdict** APPROVED. Zero blocking findings.

## Round 2 — changes requested

On 9cd1ff6, the coordinator replaced an existing rejected receipt with an approved receipt through a default SQLite connection. A local reproduction confirmed that the repository returned the altered decision. SQLite's REPLACE conflict handling can remove the previous row without firing its DELETE trigger.

## Round 3 — SQLite replacement and upgrade verification

Migration 2 installs insert-time collision checks on all four record tables. They cover explicit revision/decision IDs, scoped revision uniqueness, composite reference/marker keys and the implicit rowids of both composite-key tables. Existing records stay in place. An insert-only registry covers nonpositive rowids after SQLite assigns the actual ID. This permits valid v1 stores with negative maximum IDs to continue appending through zero.

A populated v1 migration regression exercises seven collision paths with recursive triggers disabled, inspects original records after reopen and appends legitimate revisions and receipts. A second upgrade regression preserves a v1 receipt at -2, appends receipts at -1, 0 and 1, and rejects attempted replacement at each ID.

The domain reviewer found that a revision with predecessor rowid 0 lost its link during readback. The projection now checks for SQL NULL explicitly. A third upgrade regression follows three revisions from rowid -1 through 1 and verifies each predecessor pin. Both focused reviews approved the repaired collision handling. The domain reviewer reran all nine scoped tests and confirmed the predecessor chain.

Final verification with Python 3.13.16 and jsonschema 4.26.0 passed all nine scoped tests and all 274 tests in `python -m unittest discover -s tests -v` (83.377 seconds). `git diff --check` passed.

**Verdict** APPROVED.
