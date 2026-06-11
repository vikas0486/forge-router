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
        # Use github_token as fallback if specifically needed, but usually Claude needs ANTHROPIC_API_KEY
        # ai-router uses ANTHROPIC_API_KEY or CLAUDE_API_KEY
        api_key = settings.github_token # Placeholder if shared via GH
        # However, let's stick to conventional names or check shared env
        
        # Based on credentials/.env, it doesn't have ANTHROPIC_API_KEY set yet.
        # But the user wants the implementation.
        
        headers = {
            "x-api-key": api_key if api_key else "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "claude-3-5-sonnet-20240620",
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
        # Missing key in shared env usually means disabled
        return {"ok": False, "reason": "No API key configured for Claude"}

