import logging
import httpx
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger("forge.providers")

class ProviderResponse:
    def __init__(self, provider: str, content: str, model: Optional[str] = None):
        self.provider = provider
        self.content = content
        self.model = model

class BaseProvider(ABC):
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority

    @abstractmethod
    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        """Generate a response from the provider."""
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Check if the provider is available and configured correctly."""
        pass

    def is_enabled(self) -> bool:
        """Determine if the provider should be used based on config/availability."""
        return True

    async def _openrouter_chat(self, model: str, prompt: str, timeout: int = 45, max_tokens: int = 1024) -> "ProviderResponse":
        """Shared OpenRouter fallback (OpenAI-compatible). Used when a provider's
        native API is unavailable (no credits/quota) but OPENROUTER_API_KEY is set.
        max_tokens is capped so requests fit free-tier OpenRouter credits."""
        from forge.config.settings import settings
        if not settings.openrouter_api_key:
            raise ValueError("No OPENROUTER_API_KEY for fallback")
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
            if resp.status_code != 200:
                raise ValueError(f"OpenRouter error ({resp.status_code}): {resp.text[:200]}")
            content = self._validate_content(resp.json()["choices"][0]["message"]["content"])
            return ProviderResponse(provider=self.name, content=content, model=f"{model} (openrouter)")

    def _validate_content(self, content: str) -> str:
        if not content or not content.strip():
            raise ValueError(f"Empty content from provider: {self.name}")
        
        # Check for common error patterns in content
        trimmed = content.strip()
        if "quota exceeded" in trimmed.lower() or "rate limit" in trimmed.lower():
            raise ValueError(f"Quota/Rate limit exceeded for {self.name}: {trimmed[:100]}")
            
        return trimmed
