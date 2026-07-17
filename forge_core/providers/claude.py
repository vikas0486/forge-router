import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.claude")

class ClaudeProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="claude", priority=3)
        self.url = "https://api.anthropic.com/v1/messages"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        api_key = settings.anthropic_api_key
        
        headers = {
            "x-api-key": api_key if api_key else "",
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
            content = data["content"][0]["text"]
            content = self._validate_content(content)
            return ProviderResponse(provider=self.name, content=content, model=data.get("model"))

    async def check_health(self) -> Dict[str, Any]:
        if not settings.anthropic_api_key:
            return {"ok": False, "reason": "No API key configured for Claude"}
        return {"ok": True}

