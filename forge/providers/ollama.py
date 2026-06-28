import httpx
import logging
from typing import Optional, Dict, Any, List
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.ollama")

# Intent → ordered model preference from available Ollama workers
_OLLAMA_INTENT_MODELS: Dict[str, List[str]] = {
    "code":          ["qwen3-coder:30b", "qwen2.5-coder:7b", "qwen3.6:27b", "deepseek-r1:8b", "qwen3:latest"],
    "reasoning":     ["deepseek-r1:8b",  "deepseek-r1:7b",   "qwen3.6:27b", "qwen3:latest",   "nous-hermes2:latest"],
    "agentic":       ["qwen3.6:27b",     "nous-hermes2:latest", "deepseek-r1:8b", "qwen3:latest"],
    "summarization": ["qwen3:latest",    "mistral:latest",    "llama3.1:8b", "qwen3.6:27b"],
    "chat":          ["qwen3:latest",    "mistral:latest",    "llama3.1:8b", "nous-hermes2:latest"],
}
_OLLAMA_DEFAULT = ["qwen3:latest", "mistral:latest", "llama3.1:8b", "deepseek-r1:8b"]

# Intent → ordered Ollama Cloud (Turbo) model preference. Used when an API key
# is configured. Each falls back to gpt-oss:120b, then to local models.
_OLLAMA_CLOUD_INTENT_MODELS: Dict[str, List[str]] = {
    "code":          ["qwen3-coder:480b", "gpt-oss:120b"],
    "reasoning":     ["gpt-oss:120b"],
    "agentic":       ["gpt-oss:120b"],
    "summarization": ["gpt-oss:120b", "gpt-oss:20b"],
    "chat":          ["gpt-oss:120b", "gpt-oss:20b"],
}
_OLLAMA_CLOUD_DEFAULT = "gpt-oss:120b"


class OllamaProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="ollama", priority=7)
        self._base = settings.ollama_base_url
        self._available: List[str] = []
        self._cloud_key = settings.ollama_api_key
        self._cloud_base = settings.ollama_cloud_url.rstrip("/")

    async def _get_available(self) -> List[str]:
        if self._available:
            return self._available
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{self._base}/api/tags")
                self._available = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            self._available = []
        return self._available

    def _best_model(self, available: List[str], intent: str) -> Optional[str]:
        preferred = _OLLAMA_INTENT_MODELS.get(intent, _OLLAMA_DEFAULT)
        for m in preferred:
            if m in available:
                return m
        for m in _OLLAMA_DEFAULT:
            if m in available:
                return m
        return available[0] if available else None

    def _classify_intent(self, prompt: str) -> str:
        # Reuse the router's classifier so the provider's model choice matches the
        # intent that routed the request here (lazy import avoids a circular dep).
        try:
            from forge.router.engine import classify_intent
            return classify_intent(prompt)
        except Exception:
            pass
        # Fallback heuristic if the router isn't importable for some reason.
        intent = "chat"
        for kw, cat in [("def ", "code"), ("class ", "code"), ("import ", "code"),
                         ("function", "code"), ("reason", "reasoning"), ("explain why", "reasoning"),
                         ("summarize", "summarization"), ("summary", "summarization")]:
            if kw.lower() in prompt.lower():
                intent = cat
                break
        return intent

    async def _chat(self, base: str, model: str, prompt: str, timeout: int, auth: bool = False) -> str:
        headers = {"Authorization": f"Bearer {self._cloud_key}"} if auth else {}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/api/chat",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"Ollama error ({resp.status_code}): {resp.text[:200]}")
            return resp.json()["message"]["content"]

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 90) -> ProviderResponse:
        intent = self._classify_intent(prompt)

        # Prefer Ollama Cloud (Turbo) when an API key is configured.
        if self._cloud_key:
            cloud_models = _OLLAMA_CLOUD_INTENT_MODELS.get(intent, [_OLLAMA_CLOUD_DEFAULT])
            if _OLLAMA_CLOUD_DEFAULT not in cloud_models:
                cloud_models = cloud_models + [_OLLAMA_CLOUD_DEFAULT]
            for model in cloud_models:
                try:
                    logger.info(f"[ollama-cloud] intent={intent} → model={model}")
                    content = await self._chat(self._cloud_base, model, prompt, timeout, auth=True)
                    return ProviderResponse(provider=self.name, content=self._validate_content(content), model=f"{model} (cloud)")
                except Exception as e:
                    logger.warning(f"[ollama-cloud] {model} failed: {e}")
            logger.info("[ollama-cloud] all cloud models failed — falling back to local")

        # Local models (offline / no key, or cloud unreachable)
        available = await self._get_available()
        if not available:
            raise ValueError("No Ollama models available")
        model = self._best_model(available, intent)
        logger.info(f"[ollama] intent={intent} → model={model}")
        content = await self._chat(self._base, model, prompt, timeout, auth=False)
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model=model)

    async def check_health(self) -> Dict[str, Any]:
        self._available = []  # refresh on health check
        available = await self._get_available()
        if self._cloud_key:
            # Cloud is usable as long as we have a key; report local models too if present.
            return {"ok": True, "models": available + [f"{_OLLAMA_CLOUD_DEFAULT} (cloud)"], "count": len(available) + 1}
        if available:
            return {"ok": True, "models": available, "count": len(available)}
        return {"ok": False, "reason": "Ollama not reachable or no models"}
