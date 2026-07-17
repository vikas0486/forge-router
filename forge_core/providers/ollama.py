import httpx
import logging
from typing import Optional, Dict, Any, List
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.ollama")

# Models confirmed to complete within 60s wall-clock — benchmarked on Intel i7 / 16 GB / 1.6 GB GPU.
# Excluded after benchmarking:
#   qwen3.6:27b     — 17 GB, OOM crash (exceeds 16 GB RAM)
#   qwen3-coder:30b — 75s total, exceeds wall-clock limit
#   qwen3:latest    — 92s total due to built-in thinking mode
#   deepseek-r1:8b  — 58.6s with /no_think, no safe margin for longer prompts
#
# Usable models ranked by measured speed:
#   llama3.1:8b        — 17s  ✓
#   qwen2.5-coder:7b   — 18s  ✓
#   nous-hermes2:latest — 28s  ✓

_OLLAMA_INTENT_MODELS: Dict[str, List[str]] = {
    "code":          ["qwen2.5-coder:7b",   "llama3.1:8b",       "nous-hermes2:latest"],
    "reasoning":     ["nous-hermes2:latest", "llama3.1:8b",       "qwen2.5-coder:7b"],
    "agentic":       ["nous-hermes2:latest", "llama3.1:8b",       "qwen2.5-coder:7b"],
    "summarization": ["llama3.1:8b",         "nous-hermes2:latest", "qwen2.5-coder:7b"],
    "chat":          ["llama3.1:8b",         "nous-hermes2:latest", "qwen2.5-coder:7b"],
}
_OLLAMA_DEFAULT = ["llama3.1:8b", "nous-hermes2:latest", "qwen2.5-coder:7b"]

# CPU-only performance options for Intel i7 (6-core).
# num_gpu omitted — Ollama GPU acceleration requires Apple Silicon (Metal) or NVIDIA (CUDA);
# setting it on Intel has no effect and can cause model reloads.
# num_ctx=2048 covers forge-router's short queries and reduces KV-cache memory pressure.
_PERF_OPTIONS = {
    "num_thread": 6,
    "num_ctx": 2048,
}


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

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 55) -> ProviderResponse:
        available = await self._get_available()
        if not available:
            raise ValueError("No Ollama models available")

        intent = self._detect_intent(prompt)
        model = self._best_model(available, intent)
        logger.info(f"[ollama] intent={intent} → model={model}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": _PERF_OPTIONS,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"Ollama error ({resp.status_code}): {resp.text[:200]}")
            content = resp.json()["message"]["content"]
            return ProviderResponse(provider=self.name, content=self._validate_content(content), model=model)

    def _detect_intent(self, prompt: str) -> str:
        p = prompt.lower()
        if any(kw in p for kw in ("def ", "class ", "import ", "code", "function", "bug", "error")):
            return "code"
        if any(kw in p for kw in ("reason", "explain why", "analyze", "logic", "proof", "math")):
            return "reasoning"
        if any(kw in p for kw in ("summarize", "summary", "tldr", "condense")):
            return "summarization"
        if any(kw in p for kw in ("search", "fetch", "plan", "execute", "workflow")):
            return "agentic"
        return "chat"

    async def check_health(self) -> Dict[str, Any]:
        self._available = []  # refresh on health check
        available = await self._get_available()
        if available:
            usable = [m for m in available if m not in {"nomic-embed-text:latest"}]
            return {"ok": bool(usable), "models": usable, "count": len(usable)}
        return {"ok": False, "reason": "Ollama not reachable or no models"}
