"""Gateway MVP tests — store round-trip, auth, and the /v1/messages endpoint.

The router is mocked so tests never hit real providers.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from forge_core.providers.base import ProviderResponse
from forge_gateway import create_app
from forge_gateway.store import GatewayStore


@pytest.fixture
def store():
    return GatewayStore(db_path=Path(tempfile.mkdtemp()) / "gw.db")


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store))


# ── store ──────────────────────────────────────────────────────────────────

def test_key_create_verify_revoke(store):
    key = store.create_key("alice")
    assert key.startswith("fk-")
    assert store.verify(key)["name"] == "alice"
    assert store.verify("fk-bogus") is None
    assert store.revoke("alice") is True
    assert store.verify(key) is None  # cache cleared on revoke


def test_allowed_models_recorded(store):
    key = store.create_key("bob", allowed_models=["forge/code"])
    assert store.verify(key)["allowed_models"] == ["forge/code"]


# ── auth ─────────────────────────────────────────────────────────────────────

def test_missing_key_401(client):
    r = client.post("/v1/messages", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


def test_bad_key_401(client):
    r = client.post(
        "/v1/messages",
        headers={"x-api-key": "fk-nope"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 401


# ── endpoint ─────────────────────────────────────────────────────────────────

async def _fake_route(prompt, preferred=None, context=None, **kw):
    return ProviderResponse(provider="groq", content="hi there", model="llama-3.3-70b")


def test_messages_ok_and_metered(client, store):
    key = store.create_key("cc")
    with patch("forge_gateway.app.router.route", side_effect=_fake_route):
        r = client.post(
            "/v1/messages",
            headers={"x-api-key": key},
            json={"model": "forge/auto", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "message"
    assert d["content"][0]["text"] == "hi there"
    assert d["forge_provider"] == "groq"
    assert d["usage"]["input_tokens"] >= 1
    top = store.top()
    assert top and top[0]["key_name"] == "cc" and top[0]["requests"] == 1


def test_model_allowlist_403(client, store):
    key = store.create_key("limited", allowed_models=["forge/code"])
    with patch("forge_gateway.app.router.route", side_effect=_fake_route):
        r = client.post(
            "/v1/messages",
            headers={"x-api-key": key},
            json={"model": "forge/chat", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 403


def test_empty_messages_400(client, store):
    key = store.create_key("cc2")
    r = client.post("/v1/messages", headers={"x-api-key": key}, json={"messages": []})
    assert r.status_code == 400
