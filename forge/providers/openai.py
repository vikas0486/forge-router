import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.openai")

class OpenAIProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="openai", priority=6)
        self.url = "https://api.openai.com/v1/chat/completions"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if settings.openai_api_key:
            try:
                return await self._native(prompt, timeout)
            except Exception as e:
                if settings.openrouter_api_key:
                    logger.warning(f"[openai] native failed ({e}); falling back to OpenRouter")
                else:
                    raise
        return await self._openrouter_chat("openai/gpt-4o-mini", prompt, timeout)

    async def _native(self, prompt: str, timeout: int) -> ProviderResponse:
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ]
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"OpenAI API error ({response.status_code}): {response.text}")
            data = response.json()
            content = self._validate_content(data["choices"][0]["message"]["content"])
            return ProviderResponse(provider=self.name, content=content, model=data.get("model"))

    async def check_health(self) -> Dict[str, Any]:
        if not (settings.openai_api_key or settings.openrouter_api_key):
            return {"ok": False, "reason": "Missing OPENAI_API_KEY"}
        return {"ok": True}
