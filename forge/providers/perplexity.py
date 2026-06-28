import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.perplexity")


class PerplexityProvider(BaseProvider):
    """Perplexity Sonar — OpenAI-compatible chat completions with web grounding.

    Defaults to a reasoning-tuned Sonar model, which is why the router slots it
    at the top of the reasoning chain.
    """

    def __init__(self):
        super().__init__(name="perplexity", priority=3)
        self.url = "https://api.perplexity.ai/chat/completions"
        self.model = "sonar-reasoning-pro"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 45) -> ProviderResponse:
        if not settings.perplexity_api_key:
            raise ValueError("Missing PERPLEXITY_API_KEY")

        headers = {
            "Authorization": f"Bearer {settings.perplexity_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Perplexity API error ({response.status_code}): {response.text[:300]}")
            data = response.json()
            content = self._validate_content(data["choices"][0]["message"]["content"])
            return ProviderResponse(provider=self.name, content=content, model=data.get("model", self.model))

    async def check_health(self) -> Dict[str, Any]:
        if not settings.perplexity_api_key:
            return {"ok": False, "reason": "Missing PERPLEXITY_API_KEY"}
        return {"ok": True}
