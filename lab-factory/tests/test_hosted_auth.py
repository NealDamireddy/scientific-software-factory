import asyncio
import json

import httpx
import pytest

from labfactory.hosted import application
from labfactory.hosted_auth import Access, password_hash, token_digest


@pytest.fixture(scope="module")
def reviewer_hash():
    return password_hash("test-reviewer-password")


@pytest.fixture
def config(monkeypatch, reviewer_hash):
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": reviewer_hash}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"reader": token_digest("test-agent-token")}))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "test-key-which-exceeds-thirty-two-characters")


def test_local_reviewer_can_use_portal_with_no_agents(monkeypatch):
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", "local.sqlite3")
    monkeypatch.setenv("LABFACTORY_AGENTS", "{}")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    access = Access.from_env()
    assert access.public_review and access.agents == {}
    assert access.authenticate_agent({"authorization": "Bearer unknown"}) is None
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValueError, match="Missing identities in LABFACTORY_AGENTS"):
        Access.from_env()


@pytest.mark.parametrize(("variable", "value"), [
    ("LABFACTORY_REVIEWERS", "plaintext"),
    ("LABFACTORY_REVIEWERS", "gg" * 16 + ":" + "aa" * 32),
    ("LABFACTORY_REVIEWERS", "aa" * 15 + ":" + "bb" * 32),
    ("LABFACTORY_REVIEWERS", "aa" * 16 + ":" + "bb" * 31),
    ("LABFACTORY_AGENTS", "plaintext"),
    ("LABFACTORY_AGENTS", "é" * 64),
    ("LABFACTORY_AGENTS", 12),
])
def test_invalid_environment_credentials_fail_closed(config, monkeypatch, variable, value):
    monkeypatch.setenv(variable, json.dumps({"invalid": value}))
    with pytest.raises(ValueError, match=variable) as error:
        Access.from_env()
    assert str(value) not in str(error.value)


def test_uniquely_bound_names_and_agent_credentials(config, monkeypatch):
    token = token_digest("test-agent-token")
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"one": token, "two": token.upper()}))
    with pytest.raises(ValueError, match="distinct"):
        Access.from_env()
    monkeypatch.setenv("LABFACTORY_AGENTS", f'{{"one":"{token}","one":"{token}"}}')
    with pytest.raises(ValueError, match="LABFACTORY_AGENTS"):
        Access.from_env()


def test_valid_hex_encodings_and_authentication(config, monkeypatch, reviewer_hash):
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": reviewer_hash.upper()}))
    access = Access.from_env()
    assert access.verify_password("Ada", "test-reviewer-password")
    assert access.reviewer(access.session("Ada")) == "Ada"
    assert access.authenticate_agent({"authorization": "Bearer test-agent-token"}) == "reader"
    assert not access.verify_password("Ada", "\ud800")


def test_misconfigured_auth_fails_closed_in_both_http_transports(config, monkeypatch):
    invalid_value = "unhashed-credential-from-operator"
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"reader": invalid_value}))

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="https://localhost",
        ) as client:
            session = await client.get("/api/session")
            mcp = await client.post("/mcp", headers={"Authorization": "Bearer test-agent-token"},
                                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        for response in (session, mcp):
            assert response.status_code == 503
            assert "no-store" in response.headers["cache-control"]
            assert invalid_value not in response.text
            assert "list_work_orders" not in response.text

    asyncio.run(check())
