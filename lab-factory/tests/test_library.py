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
    {"text": "\ud800", "source_id": CARY},
    {"text": "ok", "source_id": CARY, "lab_id": ""},
    {"text": "ok", "source_id": CARY, "lab_id": "  "},
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
    library.add(store, "Ben", "lab b on cary", source_id=CARY, lab_id="lab-b")
    assert library.visible(store, "lab-a")[CARY]["id"] == own["id"]
    assert library.visible(store, "lab-b")[CARY]["scope"] == "lab:lab-b"
    assert HONEY not in library.visible(store, "lab-a")
    for bad in ("", " "):
        with pytest.raises(ContextError):
            library.visible(store, bad)
        with pytest.raises(ContextError):
            library.latest(store, bad)


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
    shared = library.share(store, "Ben", own["id"], "lab-a")
    assert shared["scope"] == "shared" and shared["source_id"] == CARY
    assert shared["digest"] == own["digest"] and shared["contributed_by"] == "Ben"
    assert (shared["title"], shared["kind"], shared["origin"]) == (own["title"], own["kind"], own["origin"])
    assert count(store, "library_texts") == 1
    assert library.share(store, "Cy", own["id"], "lab-a")["id"] == shared["id"]
    with pytest.raises(NotFound):
        library.share(store, "Ben", 9999, "lab-a")


def test_share_requires_an_entry_of_the_named_lab(store):
    own = library.add(store, "Ana", TEXT, source_id=CARY, lab_id="lab-a")
    shared = library.add(store, "Ana", "Shared.", source_id=HONEY)
    entries = count(store, "library_entries")
    for entry_id, lab_id in ((own["id"], "lab-b"), (own["id"], None), (own["id"], ""), (own["id"], 5),
                             (shared["id"], "lab-a"), (shared["id"], "shared")):
        with pytest.raises(ContextError, match="Choose an entry from this lab."):
            library.share(store, "Ben", entry_id, lab_id)
    assert count(store, "library_entries") == entries


def test_catalog_paper_stays_a_paper(store):
    assert references.source("barbour-2026-honey-moisture")["kind"] == "paper"
    assert library.add(store, "Ana", TEXT, source_id="barbour-2026-honey-moisture")["kind"] == "paper"


def test_add_cannot_reach_another_labs_private_source(store):
    own = library.add(store, "Ana", "Weigh the boat.", title="Balance worksheet", lab_id="lab-a")
    for lab in ("lab-b", None):
        with pytest.raises(ContextError, match="Unknown library source."):
            library.add(store, "Bo", "x", source_id=own["source_id"], lab_id=lab)
    assert count(store, "library_entries") == 1 and count(store, "library_texts") == 1
    library.share(store, "Ana", own["id"], "lab-a")
    revised = library.add(store, "Bo", "x", source_id=own["source_id"], lab_id="lab-b")
    assert revised["scope"] == "lab:lab-b" and revised["title"] == "Balance worksheet"


def test_append_accumulates_passages_for_a_lab(store):
    first = library.append(store, "Ana", "Passage A.", source_id=CARY, lab_id="lab-a")
    assert first["revision"] == 1 and first["scope"] == "lab:lab-a"
    second = library.append(store, "Ana", "Passage B.", source_id=CARY, lab_id="lab-a")
    assert second["revision"] == 2
    assert library.get(store, second["id"])["text"] == "Passage A.\n\nPassage B."
    again = library.append(store, "Ana", "Passage A.", source_id=CARY, lab_id="lab-a")
    assert again["id"] == second["id"] and again["revision"] == 2
    assert count(store, "library_entries") == 2


def test_append_builds_on_shared_text_without_hiding_it(store):
    shared = library.add(store, "Ana", "Full manual text.", source_id=CARY)
    mine = library.append(store, "Ben", "Lab note.", source_id=CARY, lab_id="lab-a")
    assert mine["scope"] == "lab:lab-a" and mine["kind"] == shared["kind"] and mine["title"] == shared["title"]
    assert library.get(store, mine["id"])["text"] == "Full manual text.\n\nLab note."
    other = library.append(store, "Ben", "Full manual", source_id=CARY, lab_id="lab-b")
    assert other["id"] == shared["id"]
    assert library.visible(store, "lab-b")[CARY]["id"] == shared["id"]
    assert count(store, "library_entries") == 2


def test_append_rejects_a_combined_text_over_the_limit(store):
    base = "x" * (library.MAX_TEXT_BYTES - 5)
    library.add(store, "Ana", base, source_id=CARY, lab_id="lab-a")
    entries = count(store, "library_entries")
    with pytest.raises(ContextError, match="limited to"):
        library.append(store, "Ana", "y" * 10, source_id=CARY, lab_id="lab-a")
    assert count(store, "library_entries") == entries and count(store, "library_texts") == 1


def test_append_without_a_base_acts_like_add(store):
    entry = library.append(store, "Ana", "Weigh the boat.", title="Balance worksheet", lab_id="lab-a")
    assert re.fullmatch(r"contributed-[0-9a-f]{16}", entry["source_id"])
    with pytest.raises(ContextError):
        library.append(store, "Ana", "Text.", source_id="nope", lab_id="lab-a")
    with pytest.raises(ContextError):
        library.append(store, "Ana", "  ", source_id=CARY, lab_id="lab-a")
