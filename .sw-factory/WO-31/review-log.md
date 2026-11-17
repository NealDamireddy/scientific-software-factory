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
