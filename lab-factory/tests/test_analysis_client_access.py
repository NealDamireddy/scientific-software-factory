import json
import runpy
import sys
from argparse import Namespace
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from labfactory.hosted import make_portal


CLIENT = Path(__file__).resolve().parents[1] / "examples" / "analysis_client.py"


def test_portal_examples_match_cli_uploads():
    create_request = runpy.run_path(str(CLIENT))["create_request"]
    with TestClient(make_portal(CLIENT.parents[1] / "public")) as portal:
        catalog = portal.get("/examples/tabular/index.json").raise_for_status().json()
        assert {"caffeine", "density"} <= {example["folder"] for example in catalog}
        for example in catalog:
            folder = example["folder"]
            path = f"/examples/tabular/{folder}"
            payload = create_request(Namespace(example=folder, request_id=None))
            for field in ("objective", "unit", "mapping", "range_gate"):
                assert payload[field] == example[field]
            for field in ("protocol", "csv"):
                download = portal.get(f"{path}/{payload[field + '_name']}").raise_for_status()
                assert download.content == payload[field].encode("utf-8")
            control = portal.get(f"{path}/control.json").raise_for_status().json()
            assert (payload["control_expected"], payload["control_tolerance"]) == (control["expected"], control["tolerance"])


def run_client(monkeypatch, args, handler):
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(sys, "argv", [str(CLIENT), "--url", "https://lab.example.test", *args])
    runpy.run_path(str(CLIENT), run_name="__main__")


@pytest.mark.parametrize("saved_credentials", [False, True])
def test_public_reviewer_skips_credentials_and_session_mutations(monkeypatch, tmp_path, saved_credentials):
    if saved_credentials:
        monkeypatch.setenv("LAB_FACTORY_REVIEWER", "saved user")
        monkeypatch.setenv("LAB_FACTORY_REVIEWER_PASSWORD_FILE", str(tmp_path / "missing"))
    else:
        monkeypatch.delenv("LAB_FACTORY_REVIEWER", raising=False)
        monkeypatch.delenv("LAB_FACTORY_REVIEWER_PASSWORD_FILE", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Public review prompted for a name"))
    monkeypatch.setattr("getpass.getpass", lambda _: pytest.fail("Public review prompted for a password"))
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"access_mode": "public", "reviewer": "Public reviewer"})
        assert request.headers["origin"] == "https://lab.example.test"
        assert json.loads(request.content) == {"submission": 2}
        return httpx.Response(200, json={"approved": 2})

    run_client(monkeypatch, ["approve", "WO-7", "--submission", "2"], handler)
    assert calls == [("GET", "/api/session"), ("POST", "/api/orders/WO-7/approve")]


@pytest.mark.parametrize("session", [{"reviewer": None}, {"reviewer": None, "access_mode": "private"}])
def test_private_and_legacy_servers_authenticate(monkeypatch, session):
    monkeypatch.delenv("LAB_FACTORY_REVIEWER", raising=False)
    monkeypatch.delenv("LAB_FACTORY_REVIEWER_PASSWORD_FILE", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "operator")
    monkeypatch.setattr("getpass.getpass", lambda _: "example")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/session":
            return httpx.Response(200, json=session)
        if request.url.path == "/api/login":
            assert json.loads(request.content) == {"name": "operator", "password": "example"}
        return httpx.Response(200, json={})

    run_client(monkeypatch, ["list"], handler)
    assert calls == ["/api/session", "/api/login", "/api/analysis", "/api/logout"]


@pytest.mark.parametrize("status,body", [(503, {}), (200, {}), (200, ["invalid"])])
def test_failed_session_check_stops_before_prompt_or_action(monkeypatch, status, body):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Requested credentials after failed check"))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, json=body)

    with pytest.raises(SystemExit) as exc:
        run_client(monkeypatch, ["list"], handler)
    assert exc.value.code == 1
    assert calls == ["/api/session"]
