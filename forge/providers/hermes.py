import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.hermes")

# Hermes provider — NousResearch Hermes-3 identity with strong instruction-following.
# Backend: Groq llama-3.3-70b-versatile (Hermes-3 no longer hosted on Groq public API).
# Upgrade path: pull hermes3:8b via Ollama → set HERMES_BACKEND=ollama in env.

HERMES_SYSTEM = (
    "You are Hermes, an intelligent AI assistant built on the Hermes-3 model by NousResearch. "
    "You excel at precise instruction-following, structured reasoning, agentic task planning, "
    "and high-quality code generation. Always respond in a clear, structured, and complete manner."
)

OLLAMA_HERMES_MODELS = ["hermes3:latest", "hermes3:8b", "nous-hermes2:latest", "nous-hermes2"]


class HermesProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="hermes", priority=3)
        self._groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self._groq_model = "llama-3.3-70b-versatile"
        self._ollama_url = "http://localhost:11434/api/chat"

    async def _available_ollama_hermes(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get("http://localhost:11434/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
                for m in OLLAMA_HERMES_MODELS:
                    if m in names:
                        return m
        except Exception:
            pass
        return None

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        # Prefer local Hermes if available
        local_model = await self._available_ollama_hermes()
        if local_model:
            return await self._generate_ollama(prompt, local_model, timeout)
        return await self._generate_groq(prompt, timeout)

    async def _generate_groq(self, prompt: str, timeout: int) -> ProviderResponse:
        if not settings.groq_api_key:
            raise ValueError("Missing GROQ_API_KEY for Hermes provider")
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                self._groq_url,
                headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                json={
                    "model": self._groq_model,
                    "messages": [
                        {"role": "system", "content": HERMES_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                },
            )
        if resp.status_code != 200:
            raise ValueError(f"Hermes/Groq error ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=f"hermes@{self._groq_model}")

    async def _generate_ollama(self, prompt: str, model: str, timeout: int) -> ProviderResponse:
        # Local models need more headroom — 6B+ models can take 60-90s on first load
        effective_timeout = max(timeout, 90)
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            resp = await client.post(
                self._ollama_url,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": HERMES_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            )
        if resp.status_code != 200:
            raise ValueError(f"Hermes/Ollama error ({resp.status_code}): {resp.text[:200]}")
        content = resp.json()["message"]["content"]
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=f"hermes@{model}")

    async def check_health(self) -> Dict[str, Any]:
        if await self._available_ollama_hermes():
            return {"ok": True, "backend": "ollama-hermes"}
        if settings.groq_api_key:
            return {"ok": True, "backend": f"groq:{self._groq_model}"}
        return {"ok": False, "reason": "No GROQ_API_KEY and no local Hermes model"}
