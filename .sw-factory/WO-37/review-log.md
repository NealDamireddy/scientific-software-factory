# WO-37 review log

## Round 1 at 139955f

**CHANGES_REQUESTED.** The review delegate reproduced replacement of an immutable row through SQLite's INSERT OR REPLACE semantics on a default connection. The original update/delete triggers missed implicit deletes from either unique constraint. The delegate also found that nested non-JSON values exposed TypeError and that the pending PR URL line had trailing whitespace.

The four scoped unittest cases passed. The delegate verified scoped authorization before lookup, version compare-and-append, independent coding and review states, fixture portability and domain-local migration ownership.

The follow-up adds a before-insert collision trigger and tests replacements using either key on an independent connection. Serialization failures now raise ValueError. The context index has a clean pending link.

## Round 2 at c1cbc2d

**APPROVED.** The review delegate rechecked the full branch against the requested baseline, reran all four scoped tests and confirmed that rejected replacements leave history intact after reopen. A validated submission against a superseded task raised RevisionConflict. All first-round findings are resolved.

- WRV-001 and WRV-005. The fixture preserved the bounded task, scientific pins, draft state, predecessor, context snapshot and complete review history.
- WRV-004 and WRV-006. Failed and interrupted reviews, replacements, original findings, independent human resolutions and candidate-bound acceptance survived reopen. The review retry checks reject a changed kind, task or candidate.
- MCP-003. Competing clients produced one active claim. Identical concurrent requests returned one receipt. Failure, interruption, validated submission and supersession retained their own records. A worker completion claim retained the active state.
- Authorization. A denied grant and an agent attempting a human-only decision made zero storage calls. Other scope and actor checks passed in the shared suite.
- Database. Domain-only migrations preserved other tables and their schema version. Injecting an existing conflicting table rolled back initial migration. Raw update, delete and both default-connection replacement paths failed.
- Manual repository check. Initialized context and runtime repositories on one file. A separate Python interpreter reopened the order, recorded confirmed worker interruption, followed the original context pin and reopened the existing context repository. Its history was draft, assigned, interrupted.
- Verification. Scoped unittest discovery passed four tests. Compilation and git diff --check passed. The change exposes a Python repository and has no UI.
- Full suite. python3 -m unittest discover -s tests passed all 269 tests in 146.051 seconds with macOS Seatbelt and loopback access enabled. The first run under the outer sandbox could not launch Seatbelt or bind the instrument server. Final scoped tests passed after the replacement guard landed.
