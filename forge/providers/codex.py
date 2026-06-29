import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.codex")

class CodexProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="codex", priority=4)
        # Endpoint from ai-router/providers/codex.js
        self.url = "https://api.openai.com/v1/responses" 

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if settings.openai_api_key:
            try:
                return await self._native(prompt, timeout)
            except Exception as e:
                if settings.openrouter_api_key:
                    logger.warning(f"[codex] native failed ({e}); falling back to OpenRouter coder model")
                else:
                    raise
        return await self._openrouter_chat("qwen/qwen-2.5-coder-32b-instruct", prompt, timeout)

    async def _native(self, prompt: str, timeout: int) -> ProviderResponse:
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "codex-mini-latest",
            "input": prompt
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Codex API error ({response.status_code}): {response.text}")
            data = response.json()
            # Logic from ai-router/providers/codex.js
            content = data.get("output_text")
            if not content and "output" in data:
                for item in data["output"]:
                    if item.get("type") == "output_text":
                        content = item.get("text")
                        break
            content = self._validate_content(content)
            return ProviderResponse(provider=self.name, content=content, model="codex-mini-latest")

    async def check_health(self) -> Dict[str, Any]:
        if not (settings.openai_api_key or settings.openrouter_api_key):
            return {"ok": False, "reason": "Missing API key for Codex (OpenAI key required)"}
        return {"ok": True}
