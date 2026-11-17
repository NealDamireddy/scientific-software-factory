# WO-37 review log

## Round 1 at 139955f

**CHANGES_REQUESTED.** The review delegate reproduced replacement of an immutable row through SQLite's INSERT OR REPLACE semantics on a default connection. The original update/delete triggers missed implicit deletes from either unique constraint. The delegate also found that nested non-JSON values exposed TypeError and that the pending PR URL line had trailing whitespace.

The four scoped unittest cases passed. The delegate verified scoped authorization before lookup, version compare-and-append, independent coding and review states, fixture portability and domain-local migration ownership.

The follow-up adds a before-insert collision trigger and tests replacements using either key on an independent connection. Serialization failures now raise ValueError. The context index has a clean pending link.
