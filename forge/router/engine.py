import asyncio
import logging
import re
import time
from typing import List, Optional, Dict, Any, Callable
from forge.providers.base import BaseProvider, ProviderResponse
from forge.router.observability import observability
from forge.memory.knowledge_base import knowledge_base
from forge.providers.antigravity import AntigravityProvider
from forge.providers.gemini import GeminiProvider
from forge.providers.groq import GroqProvider
from forge.providers.hermes import HermesProvider
from forge.providers.sakana import SakanaProvider
from forge.providers.claude import ClaudeProvider
from forge.providers.copilot import CopilotProvider
from forge.providers.openai import OpenAIProvider
from forge.providers.codex import CodexProvider
from forge.providers.ollama import OllamaProvider

logger = logging.getLogger("forge.router")

# Intent-tuned timeouts — chat is fast, reasoning/agentic get more runway
_INTENT_TIMEOUT: Dict[str, int] = {
    "chat":          15,
    "summarization": 20,
    "code":          30,
    "reasoning":     45,
    "agentic":       60,
}

# ── Intent Classification ────────────────────────────────────────────────────

_CODE_PAT = re.compile(
    r'\b(code|function|debug|error|bug|implement|script|class|algorithm|syntax|compile|test|refactor)\b',
    re.I
)
_REASON_PAT = re.compile(
    r'\b(reason|think|analyze|explain why|logic|proof|math|calculate|solve|compare|evaluate|science)\b',
    re.I
)
_AGENT_PAT = re.compile(
    r'\b(search|browse|fetch|plan|execute|tool|agent|pipeline|workflow|automate)\b',
    re.I
)
_SUMMARY_PAT = re.compile(
    r'\b(summarize|summary|tldr|brief|condense|extract|key points)\b',
    re.I
)

def classify_intent(prompt: str) -> str:
    if _CODE_PAT.search(prompt):
        return "code"
    if _REASON_PAT.search(prompt):
        return "reasoning"
    if _AGENT_PAT.search(prompt):
        return "agentic"
    if _SUMMARY_PAT.search(prompt):
        return "summarization"
    return "chat"

# ── Provider Metadata ────────────────────────────────────────────────────────

# Maps intent → ordered list of preferred provider names
_INTENT_ROUTING: Dict[str, List[str]] = {
    "code":          ["ollama", "codex", "claude", "hermes", "openai", "groq"],
    "reasoning":     ["hermes", "claude", "openai", "groq", "sakana", "antigravity", "ollama"],
    "agentic":       ["claude", "openai", "hermes", "groq", "antigravity", "ollama"],
    "summarization": ["antigravity", "groq", "claude", "openai", "ollama"],
    "chat":          ["groq", "antigravity", "claude", "openai", "hermes", "ollama"],
}

# ── Context Transfer ─────────────────────────────────────────────────────────

class RoutingContext:
    """Carries conversation history and routing state across failovers."""
    def __init__(self, prompt: str):
        self.original_prompt = prompt
        self.intent = classify_intent(prompt)
        self.tried: List[str] = []
        self.history: List[Dict[str, str]] = []  # [{role, content}]

    def add_user_message(self, content: str):
        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, provider: str, content: str):
        self.history.append({"role": "assistant", "content": content})
        logger.info(f"[context-transfer] Response stored from {provider} ({len(content)} chars)")

    def build_prompt_with_context(self) -> str:
        if not self.history:
            return self.original_prompt
        lines = []
        for msg in self.history[-6:]:  # last 3 turns max
            lines.append(f"{msg['role'].upper()}: {msg['content']}")
        lines.append(f"USER: {self.original_prompt}")
        return "\n".join(lines)

# ── Router Engine ────────────────────────────────────────────────────────────

class RouterEngine:
    def __init__(self):
        self._all_providers: List[BaseProvider] = [
            AntigravityProvider(),
            GeminiProvider(),
            GroqProvider(),
            HermesProvider(),
            SakanaProvider(),
            ClaudeProvider(),
            CopilotProvider(),
            OpenAIProvider(),
            CodexProvider(),
            OllamaProvider(),
        ]
        self._by_name: Dict[str, BaseProvider] = {p.name: p for p in self._all_providers}

    def _ordered_for_intent(self, intent: str) -> List[BaseProvider]:
        order = _INTENT_ROUTING.get(intent, [p.name for p in self._all_providers])
        providers = []
        seen = set()
        for name in order:
            if name in self._by_name:
                providers.append(self._by_name[name])
                seen.add(name)
        # append any not in the preferred list as final fallback
        for p in sorted(self._all_providers, key=lambda x: x.priority):
            if p.name not in seen:
                providers.append(p)
        return providers

    async def route(
        self,
        prompt: str,
        preferred: Optional[str] = None,
        timeout: int = 30,
        on_progress: Optional[Callable] = None,
        image: Optional[Dict[str, Any]] = None,
        context: Optional[RoutingContext] = None,
    ) -> ProviderResponse:

        ctx = context or RoutingContext(prompt)
        intent = ctx.intent
        if timeout == 30:
            timeout = _INTENT_TIMEOUT.get(intent, 30)
        logger.info(f"[router] intent={intent} preferred={preferred} timeout={timeout}s")
        ctx.add_user_message(prompt)   # record user turn for multi-turn context

        # ── RAG: retrieve memories — skip only if KB is empty (no embed cost when cold) ──
        _kb_has_memories = (
            knowledge_base._index is not None and knowledge_base._index.ntotal > 0
        )
        if _kb_has_memories:
            memories = await knowledge_base.retrieve(prompt)
        else:
            memories = []
        memory_block = knowledge_base.build_context_block(memories)
        if memory_block:
            logger.info(f"[kb] Injecting {len(memories)} memories into prompt")
            effective_prompt = f"{memory_block}\n\n{prompt}"
        else:
            effective_prompt = ctx.build_prompt_with_context() if ctx.history else prompt

        def _progress(name: str, status: str, failed: bool = False):
            if on_progress:
                if failed:
                    on_progress(failed_provider=name, status=status)
                else:
                    on_progress(provider=name, status=status)

        def _fire_score(resp: ProviderResponse, t0: float):
            score_future = observability.score(
                prompt=prompt,
                response=resp.content,
                provider=resp.provider,
                intent=intent,
                latency_ms=round((time.time() - t0) * 1000, 1),
            )
            async def _record_and_score():
                score = await score_future
                quality = score.quality if score else 0.0
                await knowledge_base.record_interaction(
                    prompt=prompt,
                    response=resp.content,
                    provider=resp.provider,
                    intent=intent,
                    quality=quality,
                )
            asyncio.ensure_future(_record_and_score())

        # 1. Explicit preferred provider
        if preferred and preferred in self._by_name:
            p = self._by_name[preferred]
            _progress(p.name, "Using preferred provider...")
            try:
                t0 = time.time()
                resp = await p.generate(effective_prompt, timeout=timeout, image=image)
                ctx.add_assistant_message(p.name, resp.content)
                _fire_score(resp, t0)
                return resp
            except Exception as e:
                _progress(p.name, f"Preferred failed: {e}", failed=True)
                logger.warning(f"[router] preferred {preferred} failed: {e}")

        # 2. Intent-ordered fallback chain (same-category first)
        for p in self._ordered_for_intent(intent):
            if p.name in ctx.tried:
                continue
            ctx.tried.append(p.name)

            health = await p.check_health()
            if not health["ok"]:
                _progress(p.name, f"Unhealthy: {health.get('reason')}", failed=True)
                logger.debug(f"[router] skip {p.name}: {health.get('reason')}")
                continue

            _progress(p.name, f"Trying [{intent}] → {p.name}...")
            try:
                t0 = time.time()
                resp = await p.generate(effective_prompt, timeout=timeout, image=image)
                ctx.add_assistant_message(p.name, resp.content)
                logger.info(f"[router] success: {p.name} (intent={intent})")
                _fire_score(resp, t0)
                return resp
            except Exception as e:
                _progress(p.name, f"Failed: {e}", failed=True)
                logger.error(f"[router] {p.name} failed: {e}")

        raise ValueError(f"All providers failed for intent={intent}. Tried: {ctx.tried}")

    async def get_status(self) -> Dict[str, Dict[str, Any]]:
        results = {}
        for p in self._all_providers:
            results[p.name] = await p.check_health()
        return results

    def new_context(self, prompt: str) -> RoutingContext:
        return RoutingContext(prompt)


router = RouterEngine()
