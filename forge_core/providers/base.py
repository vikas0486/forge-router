import logging
import httpx
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger("forge_core.providers")

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

    def _validate_content(self, content: str) -> str:
        if not content or not content.strip():
            raise ValueError(f"Empty content from provider: {self.name}")
        
        # Check for common error patterns in content
        trimmed = content.strip()
        if "quota exceeded" in trimmed.lower() or "rate limit" in trimmed.lower():
            raise ValueError(f"Quota/Rate limit exceeded for {self.name}: {trimmed[:100]}")
            
        return trimmed
