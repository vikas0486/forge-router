import logging
import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

logger = logging.getLogger("forge_core.providers")

_CHARS_PER_TOKEN = 4


@dataclass
class UsageInfo:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated: bool = False

    @classmethod
    def from_counts(
        cls,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        estimated: bool = False,
    ) -> "UsageInfo":
        in_tok = max(0, int(input_tokens or 0))
        out_tok = max(0, int(output_tokens or 0))
        total = int(total_tokens) if total_tokens is not None else in_tok + out_tok
        total = max(total, in_tok + out_tok)
        return cls(
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=total,
            estimated=estimated,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated": self.estimated,
        }


class ProviderResponse:
    def __init__(
        self,
        provider: str,
        content: str,
        model: Optional[str] = None,
        usage: Optional[UsageInfo] = None,
    ):
        self.provider = provider
        self.content = content
        self.model = model
        self.usage = usage

class BaseProvider(ABC):
    def __init__(self, name: str, priority: int, max_context_chars: int = 60_000):
        self.name = name
        self.priority = priority
        # Input budget in characters (~4 chars/token). The router fits the
        # assembled prompt to this per provider, so a huge /repo context is
        # relevance-trimmed for tight free tiers (Groq TPM) instead of 413ing.
        self.max_context_chars = max_context_chars

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

    def _estimate_tokens(self, text: str) -> int:
        text = text or ""
        if not text.strip():
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def _estimated_usage(self, prompt: str, content: str) -> UsageInfo:
        return UsageInfo.from_counts(
            input_tokens=self._estimate_tokens(prompt),
            output_tokens=self._estimate_tokens(content),
            estimated=True,
        )

    def _usage_from_openai(self, data: Dict[str, Any]) -> Optional[UsageInfo]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return None
        if any(k in usage for k in ("input_tokens", "output_tokens")):
            return UsageInfo.from_counts(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                estimated=False,
            )
        if any(k in usage for k in ("prompt_tokens", "completion_tokens")):
            return UsageInfo.from_counts(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                estimated=False,
            )
        return None

    def _usage_from_anthropic(self, data: Dict[str, Any]) -> Optional[UsageInfo]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return None
        return UsageInfo.from_counts(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            estimated=False,
        )

    def _usage_from_ollama(self, data: Dict[str, Any]) -> Optional[UsageInfo]:
        if not isinstance(data, dict):
            return None
        if "prompt_eval_count" not in data and "eval_count" not in data:
            return None
        return UsageInfo.from_counts(
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            estimated=False,
        )
