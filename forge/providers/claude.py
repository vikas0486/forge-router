import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.claude")

class ClaudeProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="claude", priority=3)
        self.url = "https://api.anthropic.com/v1/messages"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        # Native Anthropic key must look like one (sk-ant-...); an sk-or- key here
        # means the user wants OpenRouter, so skip the native attempt.
        key = settings.anthropic_api_key or ""
        if key.startswith("sk-ant-"):
            try:
                return await self._native(prompt, timeout)
            except Exception as e:
                if settings.openrouter_api_key:
                    logger.warning(f"[claude] native failed ({e}); falling back to OpenRouter")
                else:
                    raise
        return await self._openrouter_chat("anthropic/claude-sonnet-4", prompt, timeout)

    async def _native(self, prompt: str, timeout: int) -> ProviderResponse:
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Claude API error ({response.status_code}): {response.text}")
            data = response.json()
            content = self._validate_content(data["content"][0]["text"])
            return ProviderResponse(provider=self.name, content=content, model=data.get("model"))

    async def check_health(self) -> Dict[str, Any]:
        if not (settings.anthropic_api_key or settings.openrouter_api_key):
            return {"ok": False, "reason": "No API key configured for Claude"}
        return {"ok": True}

