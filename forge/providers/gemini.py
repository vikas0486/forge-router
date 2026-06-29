import asyncio
import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.gemini")

# Gemini free-tier CLI (gemini-cli) is deprecated — migrated to Antigravity (agy).
# This provider uses the Gemini REST API directly via GEMINI_API_KEY (AIza... key).
# If your key is a CLI auth token (AQ...) it will fail; get a real key from AI Studio.

class GeminiProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="gemini", priority=1)
        self.model = "gemini-2.5-flash"
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        key = settings.gemini_api_key or ""
        if not key or key.startswith("AQ."):
            raise ValueError("GEMINI_API_KEY is a CLI auth token (AQ...), not a REST API key. Get one from https://aistudio.google.com/apikey")

        parts = [{"text": prompt}]
        if image and "data" in image and "mime_type" in image:
            parts.append({"inlineData": {"mimeType": image["mime_type"], "data": image["data"]}})

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.url}?key={key}",
                json={"contents": [{"parts": parts}]},
            )
            if resp.status_code != 200:
                raise ValueError(f"Gemini API error ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            try:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                raise ValueError(f"Unexpected Gemini response: {str(data)[:200]}")
            return ProviderResponse(provider=self.name, content=self._validate_content(content), model=self.model)

    async def check_health(self) -> Dict[str, Any]:
        key = settings.gemini_api_key or ""
        if not key:
            return {"ok": False, "reason": "Missing GEMINI_API_KEY"}
        if key.startswith("AQ."):
            return {"ok": False, "reason": "Key is a CLI auth token (AQ...) — need REST API key from AI Studio"}
        return {"ok": True}
