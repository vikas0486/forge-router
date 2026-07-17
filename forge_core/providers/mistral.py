import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.mistral")

# Mistral AI — open models (mistral-small, open-mixtral-8x7b) are free with no quota cap.
# Paid models (mistral-large, codestral) require billing.
# Using mistral-small-latest: free, strong reasoning, different architecture from LLaMA.
# API is OpenAI-compatible.

BASE_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="mistral", priority=3, max_context_chars=100_000)  # Same tier as claude/hermes

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        key = settings.mistral_api_key or ""
        if not key:
            raise ValueError("Missing MISTRAL_API_KEY")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-small-latest",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )

        if resp.status_code == 429:
            raise ValueError("Mistral rate limit hit")
        if resp.status_code != 200:
            raise ValueError(f"Mistral error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        model = data.get("model", "mistral-small-latest")
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=model)

    async def check_health(self) -> Dict[str, Any]:
        key = settings.mistral_api_key or ""
        if not key:
            return {"ok": False, "reason": "Missing MISTRAL_API_KEY — sign up at console.mistral.ai"}
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.mistral.ai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            if r.status_code == 200:
                return {"ok": True, "backend": "mistral-small-latest (free)"}
            return {"ok": False, "reason": f"Mistral auth failed ({r.status_code})"}
        except Exception as e:
            return {"ok": False, "reason": f"Mistral unreachable: {e}"}
