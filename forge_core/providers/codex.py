import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.codex")

class CodexProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="codex", priority=4, max_context_chars=300_000)

    def _api_key(self) -> Optional[str]:
        return settings.codex_api_key or settings.openai_api_key

    def _extract_content(self, data: Dict[str, Any]) -> Optional[str]:
        content = data.get("output_text")
        if content:
            return content

        for item in data.get("output", []):
            if item.get("type") == "output_text":
                return item.get("text")

            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part.get("text")

        return None

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("Missing CODEX_API_KEY or OPENAI_API_KEY")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": settings.codex_model,
            "input": prompt
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(settings.codex_api_url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Codex API error ({response.status_code}): {response.text}")

            data = response.json()
            content = self._extract_content(data)
            content = self._validate_content(content)
            return ProviderResponse(provider=self.name, content=content, model=settings.codex_model)

    async def check_health(self) -> Dict[str, Any]:
        if not self._api_key():
            return {"ok": False, "reason": "Missing CODEX_API_KEY or OPENAI_API_KEY"}
        return {"ok": True}
