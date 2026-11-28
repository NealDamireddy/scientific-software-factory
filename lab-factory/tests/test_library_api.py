import json

import pytest
from starlette.testclient import TestClient

from labfactory import library
from labfactory.hosted import application

ORIGIN = "https://localhost"
PASSWORD = "disposable test reviewer password"
CATALOG = "agilent-cary-60-user-guide"
SEARCH = "/api/references/search?instrument=agilent-cary-60&q=Check%20wavelength%20accuracy"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from labfactory.hosted_auth import password_hash, token_digest
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "portal.sqlite"))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": password_hash(PASSWORD)}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"spectrometer-agent": token_digest("disposable test worker token")}))
    with TestClient(application, base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        session.post("/api/login", json={"name": "Ada", "password": PASSWORD}).raise_for_status()
        yield session


def test_library_requires_a_reviewer(client):
    client.cookies.clear()
    assert client.get("/api/library").status_code == 401
    assert client.get("/api/library/1").status_code == 401
    assert client.post("/api/library", json={"text": "x"}).status_code == 401
    assert client.post("/api/library/1/share", json={}).status_code == 401


def test_add_list_read_and_share_over_http(client):
    shared = client.post("/api/library", json={"text": "Guide words.", "source_id": CATALOG})
    assert shared.status_code == 201 and shared.json()["scope"] == "shared"
    lab = client.post("/api/library", json={"text": "Mass steps.", "title": "Balance worksheet",
                                            "lab_id": "lab-a"})
    assert lab.status_code == 201 and lab.json()["scope"] == "lab:lab-a"

    listed = client.get("/api/library").json()["entries"]
    assert [e["id"] for e in listed] == [shared.json()["id"]]
    assert all("text" not in e for e in listed)
    both = client.get("/api/library?lab_id=lab-a").json()["entries"]
    assert {e["id"] for e in both} == {shared.json()["id"], lab.json()["id"]}
    assert all("text" not in e for e in both)
    other = client.get("/api/library?lab_id=lab-b").json()["entries"]
    assert [e["id"] for e in other] == [shared.json()["id"]]

    assert client.get(f"/api/library/{lab.json()['id']}").json()["text"] == "Mass steps."
    moved = client.post(f"/api/library/{lab.json()['id']}/share", json={})
    assert moved.status_code == 200
    assert moved.json()["scope"] == "shared" and moved.json()["digest"] == lab.json()["digest"]
    assert len(client.get("/api/library").json()["entries"]) == 2


def test_bad_requests_are_rejected(client):
    for body in ({"text": ""}, {"text": "x" * (library.MAX_TEXT_BYTES + 1), "title": "T"},
                 {"text": "x", "title": "T", "extra": 1}, {"text": "x", "source_id": "nope"},
                 {"text": "x", "title": 5}, {"title": "T"}, {"text": 5, "title": "T"}):
        assert client.post("/api/library", json=body).status_code == 400, body
    assert client.get("/api/library/999").status_code == 404
    assert client.get("/api/library/abc").status_code == 404
    assert client.get("/api/library/0").status_code == 404
    assert client.post("/api/library/abc/share", json={}).status_code == 404
    assert client.post("/api/library/999/share", json={}).status_code == 404
    foreign = client.post("/api/library", json={"text": "x", "title": "T"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403


def test_search_marks_sources_with_shared_text(client):
    before = client.get(SEARCH).json()
    ids = [f["id"] for f in before["findings"]]
    assert CATALOG in ids
    assert all("library_text" not in f for f in before["findings"])
    client.post("/api/library", json={"text": "Lab only.", "source_id": CATALOG, "lab_id": "lab-a"})
    assert all("library_text" not in f for f in client.get(SEARCH).json()["findings"])
    client.post("/api/library", json={"text": "Guide words.", "source_id": CATALOG})
    after = client.get(SEARCH).json()
    assert after["catalog_digest"] == before["catalog_digest"]
    for old, new in zip(before["findings"], after["findings"]):
        assert old["digest"] == new["digest"]
        if new["id"] == CATALOG:
            assert new["library_text"] is True
        else:
            assert "library_text" not in new
    assert all("library_text" not in f for f in client.get(SEARCH).json()["findings"] if f["id"] != CATALOG)
