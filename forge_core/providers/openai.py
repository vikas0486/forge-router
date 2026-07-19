import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.openai")

class OpenAIProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="openai", priority=6, max_context_chars=300_000)
        self.url = "https://api.openai.com/v1/chat/completions"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if not settings.openai_api_key:
            raise ValueError("Missing OPENAI_API_KEY")

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
            content = data["choices"][0]["message"]["content"]
            content = self._validate_content(content)
            return ProviderResponse(
                provider=self.name,
                content=content,
                model=data.get("model"),
                usage=self._usage_from_openai(data) or self._estimated_usage(prompt, content),
            )

    async def check_health(self) -> Dict[str, Any]:
        if not settings.openai_api_key:
            return {"ok": False, "reason": "Missing OPENAI_API_KEY"}
        return {"ok": True}
