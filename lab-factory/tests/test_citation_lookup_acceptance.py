"""Offline acceptance tests for citation lookup through the operator CLI."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SHARED_ID = "shared-reading"


@pytest.fixture
def citation_order(tmp_path):
    db = tmp_path / "factory.db"

    def cli(*args, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-m", "labfactory", "--db", str(db), *args],
            cwd=tmp_path,
            env={"PYTHONPATH": str(PACKAGE / "src"), "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        if succeeds:
            assert result.returncode == 0, result.stderr
        return result

    def put(origin, record, revision):
        path = tmp_path / f"{origin}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        assert f"revision {revision}" in cli(origin, "put", str(path)).stdout

    records = {}
    pinned = {}
    replacements = {}
    for origin, example, kind, subject in (
        ("lab", "uvvis-lab.json", "manual", "Cuvette"),
        ("experiment", "b12-experiment.json", "note", "Vial"),
    ):
        record = json.loads((PACKAGE / "examples" / example).read_text(encoding="utf-8"))
        records[origin] = record
        original = record["documents"][0]
        if origin == "lab":
            put(origin, record, 1)
        pinned[origin] = {
            **original,
            "kind": kind,
            "title": f"{subject} archive",
            "source": f"{subject} binder, page 7",
            "text": f"{subject} instructions begin here.\n\nThe final paragraph ends here.",
        }
        record["documents"] = [
            pinned[origin],
            {**pinned[origin], "id": SHARED_ID},
        ]
        put(origin, record, 2 if origin == "lab" else 1)
        replacements[origin] = {
            **original,
            "title": f"{subject} current reference",
            "source": f"{subject} current binder",
            "text": f"{subject} replacement instructions.",
        }

    order = cli(
        "wo", "create", records["experiment"]["id"],
        "--kind", "procedure", "--objective", "Review the vial A procedure",
    ).stdout.strip()

    # The familiar IDs have new contents and the collision exists only in the pinned pair.
    for origin, revision in (("lab", 3), ("experiment", 2)):
        current = replacements[origin]
        records[origin]["documents"] = [current]
        if origin == "experiment":
            records[origin]["documents"].extend([
                {**current, "id": SHARED_ID},
                {**current, "id": "current-only"},
            ])
        put(origin, records[origin], revision)

    return cli, order, records, pinned, replacements


@pytest.mark.parametrize(("origin", "revision"), [("lab", 2), ("experiment", 1)])
def test_citation_reads_exact_pinned_document_after_updates(citation_order, origin, revision):
    cli, order, records, pinned, replacements = citation_order
    before = cli("wo", "show", order).stdout
    expected = pinned[origin]

    # Each invocation starts a fresh process and opens the same database.
    first = cli("wo", "citation", order, expected["id"], succeeds=False)
    reopened = cli("wo", "citation", order, expected["id"], succeeds=False)
    assert cli("wo", "show", order).stdout == before
    for result in (first, reopened):
        assert result.returncode == 0, result.stderr
        output = result.stdout
        assert re.search(rf"(?<![\w-]){origin}(?![\w-])", output, re.IGNORECASE)
        assert records[origin]["id"] in output
        assert re.search(rf"\brevision\b\W*{revision}\b", output, re.IGNORECASE)
        for field in ("id", "kind", "title", "source"):
            assert expected[field] in output
        # Allow wrapping, indentation and escaped newlines in the display.
        display_text = " ".join(output.replace(r"\n", "\n").split())
        assert " ".join(expected["text"].split()) in display_text
        for field in ("title", "source", "text"):
            assert replacements[origin][field] not in output


@pytest.mark.parametrize(
    ("document_id", "diagnosis"),
    [
        ("never-registered", r"unknown|not found|no (?:such )?document"),
        ("current-only", r"unknown|not found|no (?:such )?document"),
        (SHARED_ID, r"ambiguous|multiple|more than one"),
    ],
)
def test_citation_requires_unique_document_in_pinned_pair(citation_order, document_id, diagnosis):
    cli, order, *_ = citation_order
    before = cli("wo", "show", order).stdout
    result = cli("wo", "citation", order, document_id, succeeds=False)
    assert cli("wo", "show", order).stdout == before
    assert result.returncode != 0
    diagnostic = result.stderr + result.stdout
    assert document_id in diagnostic, diagnostic
    assert re.search(diagnosis, diagnostic, re.IGNORECASE), diagnostic


def test_citation_reports_missing_order(citation_order):
    cli, order, _, pinned, _ = citation_order
    before = cli("wo", "show", order).stdout
    missing = "WO-999999"
    result = cli("wo", "citation", missing, pinned["lab"]["id"], succeeds=False)
    assert cli("wo", "show", order).stdout == before
    assert result.returncode != 0
    diagnostic = result.stderr + result.stdout
    assert missing in diagnostic, diagnostic
    assert re.search(r"unknown|not found|no (?:such )?(?:work )?order|does not exist",
                     diagnostic, re.IGNORECASE), diagnostic
