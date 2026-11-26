from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

import pytest

from labfactory.context import ContextError, digest, experiment_from_dict, lab_from_dict
from labfactory.store import NotFound, Revision, Store


def test_revisions_are_append_only(store, uvvis_lab_dict):
    lab = lab_from_dict(uvvis_lab_dict)
    first = store.put_lab(lab)
    assert first == Revision(1, digest(lab))

    uvvis_lab_dict["instruments"][0]["firmware"] = "2.3.2"
    revised = lab_from_dict(uvvis_lab_dict)
    second = store.put_lab(revised)
    assert second == Revision(2, digest(revised))
    assert store.get_lab(lab.id) == (revised, second)
    assert store.get_lab(lab.id, 1) == (lab, first)
    assert store.put_lab(lab) == Revision(3, digest(lab))


def test_identical_put_returns_existing_revision(store, uvvis_lab_dict, b12_experiment_dict):
    lab = lab_from_dict(uvvis_lab_dict)
    exp = experiment_from_dict(b12_experiment_dict)
    assert store.put_lab(lab) == store.put_lab(lab) == Revision(1, digest(lab))
    assert store.put_experiment(exp) == store.put_experiment(exp) == Revision(1, digest(exp))
    revised = replace(exp, goal="Record a new reference.")
    assert store.put_experiment(revised) == Revision(2, digest(revised))
    assert store.get_experiment(exp.id, 1) == (exp, Revision(1, digest(exp)))
    assert store.get_experiment(exp.id) == (revised, Revision(2, digest(revised)))


def test_experiment_requires_known_lab_and_instruments(store, uvvis_lab_dict, b12_experiment_dict):
    exp = experiment_from_dict(b12_experiment_dict)
    with pytest.raises(ContextError, match="emory-biophys"):
        store.put_experiment(exp)
    lab = lab_from_dict(uvvis_lab_dict)
    store.put_lab(lab)
    store.put_lab(replace(lab, instruments=()))
    with pytest.raises(ContextError, match="uvvis-1"):
        store.put_experiment(exp)
    with pytest.raises(NotFound):
        store.get_experiment(exp.id)


def test_put_validates_directly_constructed_records(store, uvvis_lab_dict):
    lab = lab_from_dict(uvvis_lab_dict)
    bad = replace(lab, instruments=lab.instruments * 2)
    with pytest.raises(ContextError, match="duplicate"):
        store.put_lab(bad)
    with pytest.raises(NotFound):
        store.get_lab(lab.id)


def test_missing_raises_not_found(store, uvvis_lab_dict):
    with pytest.raises(NotFound, match="nope"):
        store.get_lab("nope")
    lab = lab_from_dict(uvvis_lab_dict)
    store.put_lab(lab)
    with pytest.raises(NotFound, match="99"):
        store.get_lab(lab.id, 99)


def test_reopen_persists(tmp_path, uvvis_lab_dict):
    db = tmp_path / "lf.db"
    lab = lab_from_dict(uvvis_lab_dict)
    revised = replace(lab, name="Spectroscopy teaching lab")
    with Store(db) as writer:
        writer.put_lab(lab)
        second = writer.put_lab(revised)
    with Store(db) as reader:
        assert reader.get_lab(lab.id) == (revised, second)


def test_transaction_rolls_back_on_exception(store, uvvis_lab_dict):
    lab = lab_from_dict(uvvis_lab_dict)
    first = store.put_lab(lab)
    with pytest.raises(RuntimeError, match="abort"):
        with store.transaction() as connection:
            connection.execute("DELETE FROM records")
            raise RuntimeError("abort")
    assert store.get_lab(lab.id) == (lab, first)


def test_first_open_race_preserves_both_writers(tmp_path, uvvis_lab_dict):
    path = tmp_path / "new.db"
    lab = lab_from_dict(uvvis_lab_dict)
    ready = threading.Barrier(2)

    def write(lab_id):
        ready.wait(timeout=5)
        with Store(path) as store:
            return store.put_lab(replace(lab, id=lab_id))

    ids = ["lab-a", "lab-b"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(write, ids))
    with Store(path) as store:
        assert [store.get_lab(id)[1] for id in ids] == revisions
