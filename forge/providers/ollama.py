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


class OllamaProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="ollama", priority=7)
        self._base = settings.ollama_base_url
        self._available: List[str] = []

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

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 90) -> ProviderResponse:
        available = await self._get_available()
        if not available:
            raise ValueError("No Ollama models available")

        # Intent is carried in the prompt prefix block if injected by router; extract if possible
        intent = "chat"
        if "[FORGE MEMORY" in prompt or prompt.startswith("USER:"):
            intent = "chat"
        for kw, cat in [("def ", "code"), ("class ", "code"), ("import ", "code"),
                         ("reason", "reasoning"), ("explain why", "reasoning"),
                         ("summarize", "summarization"), ("summary", "summarization")]:
            if kw.lower() in prompt.lower():
                intent = cat
                break

        model = self._best_model(available, intent)
        logger.info(f"[ollama] intent={intent} → model={model}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"Ollama error ({resp.status_code}): {resp.text[:200]}")
            content = resp.json()["message"]["content"]
            return ProviderResponse(provider=self.name, content=self._validate_content(content), model=model)

    async def check_health(self) -> Dict[str, Any]:
        self._available = []  # refresh on health check
        available = await self._get_available()
        if available:
            return {"ok": True, "models": available, "count": len(available)}
        return {"ok": False, "reason": "Ollama not reachable or no models"}
