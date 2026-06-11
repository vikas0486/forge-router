import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.ollama")

class OllamaProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="ollama", priority=7) # Final fallback

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        url = f"{settings.ollama_base_url}/api/generate"
        
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    raise ValueError(f"Ollama API error ({response.status_code}): {response.text}")

                data = response.json()
                content = data.get("response", "")
                content = self._validate_content(content)
                return ProviderResponse(provider=self.name, content=content, model=data.get("model"))
            except httpx.ConnectError:
                raise ValueError("Could not connect to Ollama. Is it running?")

    async def check_health(self) -> Dict[str, Any]:
        url = f"{settings.ollama_base_url}/api/tags"
        async with httpx.AsyncClient(timeout=2) as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    models = [m["name"] for m in response.json().get("models", [])]
                    return {"ok": True, "details": f"Models: {', '.join(models)}"}
                return {"ok": False, "reason": f"Ollama returned {response.status_code}"}
            except Exception as e:
                return {"ok": False, "reason": f"Connection failed: {str(e)}"}
