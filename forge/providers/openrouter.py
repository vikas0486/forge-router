import httpx
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.openrouter")

# OpenRouter aggregates 200+ hosted models via a single OpenAI-compatible endpoint.
# Key value: gives cloud access to large models (DeepSeek-R1 671B, Qwen-32B coder)
# that are impossible to run locally on 16 GB RAM.

_INTENT_MODELS: Dict[str, str] = {
    "code":          "qwen/qwen-2.5-coder-32b-instruct",  # 32B code specialist
    "reasoning":     "deepseek/deepseek-r1",               # Full 671B R1 — far better than local 8b
    "agentic":       "meta-llama/llama-3.3-70b-instruct",
    "summarization": "meta-llama/llama-3.3-70b-instruct",
    "chat":          "meta-llama/llama-3.3-70b-instruct",
}
_DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="openrouter", priority=5)

    def _model_for(self, prompt: str) -> str:
        p = prompt.lower()
        if any(k in p for k in ("def ", "class ", "import ", "code", "function", "bug", "error", "implement", "script")):
            return _INTENT_MODELS["code"]
        if any(k in p for k in ("reason", "explain why", "analyze", "logic", "proof", "math", "calculate", "solve")):
            return _INTENT_MODELS["reasoning"]
        if any(k in p for k in ("summarize", "summary", "tldr", "condense", "extract")):
            return _INTENT_MODELS["summarization"]
        if any(k in p for k in ("search", "fetch", "plan", "execute", "workflow", "agent", "automate")):
            return _INTENT_MODELS["agentic"]
        return _DEFAULT_MODEL

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        key = settings.openrouter_api_key or ""
        if not key:
            raise ValueError("Missing OPENROUTER_API_KEY")

        model = self._model_for(prompt)
        logger.info(f"[openrouter] model={model}")

        messages = [{"role": "user", "content": prompt}]

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/vikash/forge-router",
                    "X-Title": "Forge Router",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                },
            )

        if resp.status_code != 200:
            raise ValueError(f"OpenRouter error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        used_model = data.get("model", model)
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=used_model)

    async def check_health(self) -> Dict[str, Any]:
        key = settings.openrouter_api_key or ""
        if not key:
            return {"ok": False, "reason": "Missing OPENROUTER_API_KEY"}
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            if r.status_code == 200:
                return {"ok": True, "backend": "openrouter.ai"}
            return {"ok": False, "reason": f"OpenRouter auth failed ({r.status_code})"}
        except Exception as e:
            return {"ok": False, "reason": f"OpenRouter unreachable: {e}"}
