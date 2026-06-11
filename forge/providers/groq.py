import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.groq")

class GroqProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="groq", priority=2)
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if not settings.groq_api_key:
            raise ValueError("Missing GROQ_API_KEY")

        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            
            if response.status_code != 200:
                raise ValueError(f"Groq API error ({response.status_code}): {response.text}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            content = self._validate_content(content)
            
            return ProviderResponse(provider=self.name, content=content, model=data.get("model"))

    async def check_health(self) -> Dict[str, Any]:
        if not settings.groq_api_key:
            return {"ok": False, "reason": "Missing GROQ_API_KEY"}
        return {"ok": True}
