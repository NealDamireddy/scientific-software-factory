# WO-9 implementation plan

## Summary

Verify concentration and time-course applications independently in the offline sandbox. Commit immutable artifact bytes, a verified manifest and its scoped active pointer in a single local transaction.

## Code reuse and package structure

Reuse factory.sandbox.execute, the three B12 artifact names, source revision convention and SHA-256 helpers. Add a versioned scientific contract and independent verifier cases, a release service/repository, a standalone test candidate and backend tests. Leave scheduling, worker generation, acquisition and B12 contracts with their owners.

## Components and flow

The trusted WO-8 caller supplies its approved compiled recipe, pinned context, public instrument projection and candidate metadata separately from worker artifact bytes. ScientificReleaseVerifier checks digests, provenance, views and exact JSON recipe equality, then invokes the candidate on independent public fixtures in isolation. Cases cover raw counts, calibration standards and frozen calibration, real timestamps, sample SD, invalid data and retained review reasons. ReleaseRepository stores verified bytes and returns the current release by lab, project and experiment type. Its analysis entry point uses the retained source in the same sandbox.

## Steps

1. Define the versioned input/output contract and deterministic numerical cases at the WO-7 public record boundary.
2. Implement independent checks and atomic publication using SQLite and content-addressed records.
3. Exercise both passing and defective fixture candidates, isolation, artifact tampering and preserve-on-failure behavior.
4. Review the branch diff, run B12 regressions and record PR and evidence in 8090.

## Testing

Run focused unittest cases against temporary repositories and real sandbox processes. Run the full unittest discovery suite including B12 optics, follow-up, replay and sandbox. Inspect a verified manifest and analysis output, and check syntax and whitespace.

The implemented handoff exposes verify_release in factory/scientific_release.py and analyze_release in factory/scientific_analysis.py. The latter loads and digest-checks retained bytes, projects public inputs and validates result rows after sandbox execution. The versioned verifier fixtures are in factory/scientific_contract.py, with a separately written standalone candidate under tests/fixtures.
