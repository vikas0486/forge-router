import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.groq")

# Intent-routed models (benchmarked July 2026 on this account):
#   openai/gpt-oss-120b       — 120B MoE, 0.40s, native reasoning → code/reasoning/agentic
#   llama-3.3-70b-versatile   — 0.52s, clean output, higher TPM   → chat/summarization
# Rejected: qwen3-32b (wrong code, drowns in thinking tokens),
#           qwen3.6-27b (correct but burns full token budget on thinking),
#           llama-4-scout-17b (fast but smaller and no win over the two above).
# Free-tier TPM: gpt-oss-120b 8_000, llama-3.3 12_000 — max_context_chars 24_000
# (~6K tokens) keeps prompts inside BOTH limits with response headroom.

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_REASONING_MODEL = "openai/gpt-oss-120b"


class GroqProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="groq", priority=2, max_context_chars=24_000)
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def _model_for(self, prompt: str) -> str:
        p = prompt.lower()
        if any(k in p for k in ("def ", "class ", "import ", "code", "function", "bug", "error",
                                "implement", "script", "refactor", "debug",
                                "reason", "explain why", "analyze", "logic", "proof", "math", "solve",
                                "plan", "execute", "workflow", "agent", "automate")):
            return _REASONING_MODEL
        return _DEFAULT_MODEL

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if not settings.groq_api_key:
            raise ValueError("Missing GROQ_API_KEY")

        model = self._model_for(prompt)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        if model == _REASONING_MODEL:
            # Keep reasoning short and never cap tokens — a cap can exhaust the
            # budget inside the reasoning field and return empty content.
            payload["reasoning_effort"] = "low"
        logger.info(f"[groq] model={model}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code != 200:
                raise ValueError(f"Groq API error ({response.status_code}): {response.text}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            content = self._validate_content(content)   # empty content → fallback to next provider
            return ProviderResponse(
                provider=self.name,
                content=content,
                model=data.get("model"),
                usage=self._usage_from_openai(data) or self._estimated_usage(prompt, content),
            )

    async def check_health(self) -> Dict[str, Any]:
        if not settings.groq_api_key:
            return {"ok": False, "reason": "Missing GROQ_API_KEY"}
        return {"ok": True, "backend": f"{_DEFAULT_MODEL} + {_REASONING_MODEL} (intent-routed)"}
