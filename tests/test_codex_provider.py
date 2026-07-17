import pytest

from forge.config.settings import settings
from forge.providers.codex import CodexProvider


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "Codex response"}
                    ]
                }
            ]
        }


class FakeAsyncClient:
    last_request = None

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers, json):
        FakeAsyncClient.last_request = {
            "url": url,
            "headers": headers,
            "json": json,
        }
        return FakeResponse()


@pytest.mark.asyncio
async def test_codex_prefers_dedicated_api_key(monkeypatch):
    monkeypatch.setattr(settings, "codex_api_key", "codex-token")
    monkeypatch.setattr(settings, "openai_api_key", "openai-token")
    monkeypatch.setattr(settings, "codex_api_url", "https://codex.example.test/responses")
    monkeypatch.setattr(settings, "codex_model", "codex-test-model")
    monkeypatch.setattr("forge.providers.codex.httpx.AsyncClient", FakeAsyncClient)

    response = await CodexProvider().generate("hello")

    assert response.content == "Codex response"
    assert response.model == "codex-test-model"
    assert FakeAsyncClient.last_request["url"] == "https://codex.example.test/responses"
    assert FakeAsyncClient.last_request["headers"]["Authorization"] == "Bearer codex-token"
    assert FakeAsyncClient.last_request["json"] == {
        "model": "codex-test-model",
        "input": "hello",
    }


@pytest.mark.asyncio
async def test_codex_health_accepts_dedicated_api_key(monkeypatch):
    monkeypatch.setattr(settings, "codex_api_key", "codex-token")
    monkeypatch.setattr(settings, "openai_api_key", None)

    assert await CodexProvider().check_health() == {"ok": True}
