import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.cerebras")

# Cerebras Cloud — wafer-scale chip inference.
# Available models (verified via /v1/models): gpt-oss-120b, zai-glm-4.7
# API is OpenAI-compatible.

BASE_URL = "https://api.cerebras.ai/v1/chat/completions"


class CerebrasProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="cerebras", priority=1, max_context_chars=48_000)  # Between antigravity(0) and groq(2)

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        key = settings.cerebras_api_key or ""
        if not key:
            raise ValueError("Missing CEREBRAS_API_KEY")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-oss-120b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )

        if resp.status_code == 429:
            raise ValueError("Cerebras daily quota exceeded — free tier limit reached")
        if resp.status_code != 200:
            raise ValueError(f"Cerebras error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        model = data.get("model", "gpt-oss-120b")
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=model)

    async def check_health(self) -> Dict[str, Any]:
        key = settings.cerebras_api_key or ""
        if not key:
            return {"ok": False, "reason": "Missing CEREBRAS_API_KEY — sign up at cloud.cerebras.ai"}
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.cerebras.ai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            if r.status_code == 200:
                return {"ok": True, "backend": "cerebras — gpt-oss-120b"}
            return {"ok": False, "reason": f"Cerebras auth failed ({r.status_code})"}
        except Exception as e:
            return {"ok": False, "reason": f"Cerebras unreachable: {e}"}
