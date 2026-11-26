"""Separate named identities for human reviewers and remote MCP workers."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets

import jwt

from .context import unique_fields

SESSION_COOKIE = "__Host-labfactory-review"
SESSION_SECONDS = 8 * 60 * 60
PUBLIC_REVIEWER = "Public reviewer"
ITERATIONS = 600_000
_AGENT_DIGEST = re.compile(r"[a-fA-F0-9]{64}")
_REVIEWER_HASH = re.compile(r"(?:[a-fA-F0-9]{2}){16,}:[a-fA-F0-9]{64}")


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = secrets.token_bytes(16) if salt is None else salt
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{salt.hex()}:{derived.hex()}"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _identities(variable: str, pattern: re.Pattern[str]) -> dict[str, str]:
    try:
        data = json.loads(os.environ[variable], object_pairs_hook=unique_fields)
    except (ValueError, RecursionError):
        raise ValueError(f"Invalid identity map in {variable}") from None
    if not isinstance(data, dict) or not data:
        raise ValueError(f"Missing identities in {variable}")
    for name, value in data.items():
        if (not name.strip() or not name.isprintable() or not isinstance(value, str)
                or not pattern.fullmatch(value)):
            raise ValueError(f"Invalid identity in {variable}")
    return {name: value.lower() for name, value in data.items()}


@dataclass(frozen=True)
class Access:
    reviewers: dict[str, str]
    agents: dict[str, str]
    session_key: str | None

    @property
    def public_review(self) -> bool:
        return self.session_key is None

    @classmethod
    def from_env(cls):
        agents = _identities("LABFACTORY_AGENTS", _AGENT_DIGEST)
        if len(set(agents.values())) != len(agents):
            raise ValueError("Each agent must have a distinct token digest")
        if os.environ.get("LABFACTORY_PUBLIC_REVIEW") == "1":
            return cls({}, agents, None)
        key = os.environ["LABFACTORY_SESSION_KEY"]
        if len(key) < 32:
            raise ValueError("Session key is too short")
        reviewers = _identities("LABFACTORY_REVIEWERS", _REVIEWER_HASH)
        return cls(reviewers, agents, key)

    def authenticate_agent(self, headers) -> str | None:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 1024:
            return None
        digest = token_digest(token)
        return next((name for name, value in self.agents.items() if hmac.compare_digest(value, digest)), None)

    def verify_password(self, name: str, password: str) -> bool:
        if not isinstance(name, str) or not isinstance(password, str) or not 0 < len(password) <= 1024:
            return False
        # Spend the same derivation cost for unknown names.
        reference = self.reviewers.get(name, "00" * 16 + ":" + "00" * 32)
        salt = bytes.fromhex(reference.split(":")[0])
        try:
            derived = password_hash(password, salt)
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(derived, reference) and name in self.reviewers

    def session(self, name: str) -> str:
        if self.session_key is None:
            raise ValueError("Public review does not issue named sessions")
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {"sub": name, "aud": "labfactory-review", "iat": now, "exp": now + timedelta(seconds=SESSION_SECONDS),
             "version": token_digest(self.reviewers[name])}, self.session_key, algorithm="HS256",
        )

    def reviewer(self, cookie: str | None) -> str | None:
        if self.public_review:
            return PUBLIC_REVIEWER
        if not cookie:
            return None
        try:
            claims = jwt.decode(cookie, self.session_key, algorithms=["HS256"], audience="labfactory-review",
                                options={"require": ["sub", "exp", "iat", "version"]})
        except jwt.InvalidTokenError:
            return None
        name = claims["sub"]
        if name in self.reviewers and claims["version"] == token_digest(self.reviewers[name]):
            return name
        return None
