"""Run the unittest suite and fail if anything outside the PostgreSQL contracts is skipped.

    python scripts/run_tests.py

The PostgreSQL contracts skip without a disposable cluster; CI runs them with no skips
in its own job (tests/fixtures/postgres/run.sh). Every other test must execute, so a
missing sandbox, scheduler or fixture can't turn a gate into a silent skip.
"""
import sys
import unittest

ALLOWED_SKIPS = ("tests.test_postgres_",)


def main():
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    unexpected = [(test.id(), reason) for test, reason in result.skipped
                  if not test.id().startswith(ALLOWED_SKIPS)]
    for name, reason in unexpected:
        print(f"Unexpected skip: {name}: {reason}", file=sys.stderr)
    if not result.testsRun or unexpected or not result.wasSuccessful():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
