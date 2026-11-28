import hashlib
import re

import pytest

from labfactory import library, references
from labfactory.context import ContextError
from labfactory.store import NotFound

CARY = "agilent-cary-60-user-guide"
HONEY = "ihc-2009-honey-moisture"
TEXT = "Set the wavelength to 550 nm.\nZero with the blank."


def count(store, table):
    return store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_add_shared_text_to_a_catalog_source(store):
    entry = library.add(store, "Ana", TEXT, source_id=CARY)
    catalog = references.source(CARY)
    assert entry["scope"] == "shared" and entry["revision"] == 1 and entry["kind"] == "manual"
    assert entry["title"] == catalog["title"] and entry["origin"] == catalog["url"]
    assert entry["document_id"] == "library:" + CARY and entry["source_id"] == CARY
    assert entry["bytes"] == len(TEXT.encode("utf-8")) and entry["contributed_by"] == "Ana"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["digest"])
    assert entry["digest"] == hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    assert library.get(store, entry["id"])["text"] == TEXT
    assert count(store, "library_texts") == 1


def test_catalog_procedure_becomes_a_note(store):
    assert library.add(store, "Ana", TEXT, source_id=HONEY)["kind"] == "note"


def test_same_text_is_stored_once_and_is_idempotent(store):
    first = library.add(store, "Ana", TEXT, source_id=CARY)
    assert library.add(store, "Ben", TEXT, source_id=CARY)["id"] == first["id"]
    assert count(store, "library_entries") == 1
    library.add(store, "Ana", TEXT, source_id=HONEY)
    assert count(store, "library_texts") == 1 and count(store, "library_entries") == 2


def test_new_text_appends_a_revision_and_keeps_the_old_one(store):
    first = library.add(store, "Ana", TEXT, source_id=CARY)
    second = library.add(store, "Ana", TEXT + "\nRead.", source_id=CARY)
    assert second["revision"] == 2 and second["id"] != first["id"]
    assert library.get(store, first["id"])["text"] == TEXT


def test_contributed_source_gets_a_stable_id(store):
    entry = library.add(store, "Ana", "Weigh the boat.", title="Balance worksheet", lab_id="lab-a")
    assert re.fullmatch(r"contributed-[0-9a-f]{16}", entry["source_id"])
    assert entry["scope"] == "lab:lab-a" and entry["kind"] == "note"
    assert entry["origin"] == "Supplied by Ana"
    again = library.add(store, "Ana", "Tare first.", title="BALANCE worksheet", lab_id="lab-a")
    assert again["source_id"] == entry["source_id"] and again["revision"] == 2
    other = library.add(store, "Ana", "Weigh the boat.", title="Balance worksheet", lab_id="lab-b")
    assert other["source_id"] != entry["source_id"]
    third = library.add(store, "Ana", "Zero.", source_id=entry["source_id"], lab_id="lab-a")
    assert third["revision"] == 3 and third["title"] == "Balance worksheet"


@pytest.mark.parametrize("kwargs", [
    {"text": ""}, {"text": "   "}, {"text": "a\x00b"}, {"text": "x" * (library.MAX_TEXT_BYTES + 1)},
    {"text": 5}, {"text": "ok"}, {"text": "ok", "title": "t" * 251},
    {"text": "ok", "source_id": "nope"},
])
def test_add_rejects_bad_text(store, kwargs):
    text = kwargs.pop("text")
    with pytest.raises(ContextError):
        library.add(store, "Ana", text, **kwargs)
    assert count(store, "library_texts") == 0 and count(store, "library_entries") == 0


def test_visible_prefers_the_labs_own_entry_and_hides_other_labs(store):
    shared = library.add(store, "Ana", "shared text", source_id=CARY)
    own = library.add(store, "Ana", "lab a text", source_id=CARY, lab_id="lab-a")
    hidden = library.add(store, "Ben", "lab b text", source_id=HONEY, lab_id="lab-b")
    seen = library.visible(store, "lab-a")
    assert seen[CARY]["id"] == own["id"] and HONEY not in seen
    assert library.visible(store, "lab-b")[CARY]["id"] == shared["id"]
    assert library.visible(store, "lab-b")[HONEY]["id"] == hidden["id"]
    assert set(library.visible(store, None)) == {CARY}
    assert library.visible(store, None)[CARY]["id"] == shared["id"]
    assert set(library.visible(store, "lab-a", [CARY])) == {CARY}
    assert library.visible(store, "lab-a", [HONEY]) == {}


def test_latest_lists_one_row_per_source_and_scope(store):
    library.add(store, "Ana", "v1", source_id=CARY)
    newest = library.add(store, "Ana", "v2", source_id=CARY)
    own = library.add(store, "Ana", "mine", source_id=CARY, lab_id="lab-a")
    assert [e["id"] for e in library.latest(store)] == [newest["id"]]
    rows = library.latest(store, "lab-a")
    assert [e["id"] for e in rows] == [own["id"], newest["id"]]  # ordered by title, then scope: "lab:lab-a" < "shared"
    assert all("text" not in e for e in rows)


def test_share_points_at_the_same_text(store):
    own = library.add(store, "Ana", TEXT, source_id=CARY, lab_id="lab-a")
    shared = library.share(store, "Ben", own["id"])
    assert shared["scope"] == "shared" and shared["source_id"] == CARY
    assert shared["digest"] == own["digest"] and shared["contributed_by"] == "Ben"
    assert (shared["title"], shared["kind"], shared["origin"]) == (own["title"], own["kind"], own["origin"])
    assert count(store, "library_texts") == 1
    assert library.share(store, "Cy", own["id"])["id"] == shared["id"]
    assert library.share(store, "Cy", shared["id"]) == shared
    with pytest.raises(NotFound):
        library.share(store, "Ben", 9999)


def test_catalog_paper_stays_a_paper(store):
    assert references.source("barbour-2026-honey-moisture")["kind"] == "paper"
    assert library.add(store, "Ana", TEXT, source_id="barbour-2026-honey-moisture")["kind"] == "paper"
