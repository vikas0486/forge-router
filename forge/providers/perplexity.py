import httpx
import logging
from typing import Optional, Dict, Any, Tuple
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.perplexity")


class PerplexityProvider(BaseProvider):
    """Perplexity Sonar — OpenAI-compatible chat completions with web grounding.

    Uses the direct Perplexity API when PERPLEXITY_API_KEY is set, otherwise
    runs Perplexity models through OpenRouter (OPENROUTER_API_KEY). Slotted at
    the top of the reasoning chain.
    """

    DIRECT_URL = "https://api.perplexity.ai/chat/completions"
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self):
        super().__init__(name="perplexity", priority=3)

    def _config(self) -> Optional[Tuple[str, str, str, Optional[int]]]:
        """(url, api_key, model, max_tokens) — direct key preferred, else OpenRouter."""
        if settings.perplexity_api_key:
            return self.DIRECT_URL, settings.perplexity_api_key, "sonar-reasoning-pro", None
        if settings.openrouter_api_key:
            # max_tokens capped so requests stay within OpenRouter's affordable budget.
            return self.OPENROUTER_URL, settings.openrouter_api_key, "perplexity/sonar-pro", 1024
        return None

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 45) -> ProviderResponse:  # timeout overridden by router._INTENT_TIMEOUT (45s reasoning, 60s agentic)
        cfg = self._config()
        if not cfg:
            raise ValueError("Missing PERPLEXITY_API_KEY or OPENROUTER_API_KEY")
        url, key, model, max_tokens = cfg

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Perplexity API error ({response.status_code}): {response.text[:300]}")
            data = response.json()
            content = self._validate_content(data["choices"][0]["message"]["content"])
            return ProviderResponse(provider=self.name, content=content, model=data.get("model", model))

    async def check_health(self) -> Dict[str, Any]:
        if not (settings.perplexity_api_key or settings.openrouter_api_key):
            return {"ok": False, "reason": "Missing PERPLEXITY_API_KEY or OPENROUTER_API_KEY"}
        return {"ok": True}
