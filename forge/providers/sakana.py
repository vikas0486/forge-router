import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.sakana")

# Sakana AI — fugu/fugu-ultra models via api.sakana.ai (requires paid subscription).
# Local fallback: qwen3.6:27b or deepseek-r1:8b via Ollama — closest in reasoning profile.

SAKANA_LOCAL_FALLBACKS = ["qwen3.6:27b", "deepseek-r1:8b", "qwen3:latest"]

SAKANA_SYSTEM = (
    "You are a precise, analytical AI assistant. "
    "Focus on structured reasoning, scientific accuracy, and complete responses."
)


class SakanaProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="sakana", priority=4)
        self.base_url = "https://api.sakana.ai/v1"
        self._ollama_url = "http://localhost:11434/api/chat"
        self._ollama_tags_url = "http://localhost:11434/api/tags"

    async def _available_local(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(self._ollama_tags_url)
                names = [m["name"] for m in r.json().get("models", [])]
                for m in SAKANA_LOCAL_FALLBACKS:
                    if m in names:
                        return m
        except Exception:
            pass
        return None

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        key = settings.sakana_api_key or ""

        # Try Sakana hosted API first
        if key:
            try:
                return await self._generate_api(prompt, key, timeout)
            except ValueError as e:
                if "subscription" in str(e).lower() or "429" in str(e):
                    logger.warning("[sakana] No active subscription — falling back to local model")
                else:
                    raise

        # Local fallback
        local = await self._available_local()
        if not local:
            raise ValueError("Sakana API requires subscription and no local fallback model available")
        return await self._generate_local(prompt, local, timeout)

    async def _generate_api(self, prompt: str, key: str, timeout: int) -> ProviderResponse:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "fugu-ultra",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )
        if resp.status_code != 200:
            raise ValueError(f"Sakana API error ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=data.get("model", "fugu-ultra"))

    async def _generate_local(self, prompt: str, model: str, timeout: int) -> ProviderResponse:
        effective_timeout = max(timeout, 90)
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            resp = await client.post(
                self._ollama_url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SAKANA_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            )
        if resp.status_code != 200:
            raise ValueError(f"Sakana/local error ({resp.status_code}): {resp.text[:200]}")
        content = resp.json()["message"]["content"]
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=f"sakana-local@{model}")

    async def check_health(self) -> Dict[str, Any]:
        key = settings.sakana_api_key or ""
        if key:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {key}"})
                    if r.status_code == 200:
                        return {"ok": True, "backend": "sakana-api"}
            except Exception:
                pass

        local = await self._available_local()
        if local:
            return {"ok": True, "backend": f"local:{local}"}

        return {"ok": False, "reason": "No Sakana subscription and no local fallback model"}
