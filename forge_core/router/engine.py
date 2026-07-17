import asyncio
import logging
import re
import time
from typing import List, Optional, Dict, Any, Callable
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.router.observability import observability
from forge_core.memory.knowledge_base import knowledge_base
from forge_core.providers.antigravity import AntigravityProvider
from forge_core.providers.cerebras import CerebrasProvider
from forge_core.providers.groq import GroqProvider
from forge_core.providers.hermes import HermesProvider
from forge_core.providers.mistral import MistralProvider
from forge_core.providers.claude import ClaudeProvider
from forge_core.providers.openrouter import OpenRouterProvider
from forge_core.providers.copilot import CopilotProvider
from forge_core.providers.openai import OpenAIProvider
from forge_core.providers.codex import CodexProvider
from forge_core.providers.ollama import OllamaProvider

logger = logging.getLogger("forge_core.router")

# Intent-tuned timeouts — chat is fast, reasoning/agentic get more runway
_INTENT_TIMEOUT: Dict[str, int] = {
    "chat":          15,
    "summarization": 20,
    "code":          30,
    "reasoning":     45,
    "agentic":       60,
}

# Hard wall-clock cap per provider — if any provider (including local Ollama) exceeds
# this, the router cancels it and tries the next in the fallback chain.
WALL_CLOCK_TIMEOUT = 60

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
    "chat":          ["groq", "cerebras", "antigravity", "claude", "mistral", "openai", "hermes", "openrouter", "ollama"],
    "summarization": ["antigravity", "groq", "cerebras", "claude", "mistral", "openrouter", "openai", "ollama"],
    "code":          ["codex", "claude", "hermes", "openrouter", "mistral", "openai", "groq", "cerebras", "ollama"],
    "reasoning":     ["hermes", "claude", "openrouter", "mistral", "openai", "groq", "cerebras", "antigravity", "ollama"],
    "agentic":       ["claude", "openai", "hermes", "openrouter", "groq", "cerebras", "mistral", "antigravity", "ollama"],
}

# ── Adaptive Context Fitting ─────────────────────────────────────────────────
# File/repo context is split into "### " sections; when it exceeds a provider's
# input budget, the sections most relevant to the prompt are kept. This lets
# tight free tiers (Groq TPM 12K) work with huge /repo contexts that big-window
# providers (Claude, GPT-4o) receive in full.

_SECTION_SPLIT_RE = re.compile(r'\n(?=### )')
_TERM_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{3,}')


def shrink_context(prefix: str, prompt: str, budget: int) -> str:
    """Fit a file/repo context block into `budget` chars, preferring sections
    relevant to the prompt. Returns prefix unchanged when it already fits."""
    if len(prefix) <= budget:
        return prefix
    if budget < 500:
        return ""

    sections = _SECTION_SPLIT_RE.split(prefix)
    head, body = sections[0], sections[1:]
    if len(head) > budget:
        return head[: budget - 60] + "\n... [context header truncated to fit model limit]"

    terms = {t.lower() for t in _TERM_RE.findall(prompt)}

    def score(sec: str) -> float:
        first_line = sec.split("\n", 1)[0].lower()   # "### File: `path`" / "### `rel`"
        low = sec[:4000].lower()
        return (
            sum(3.0 for t in terms if t in first_line)
            + sum(min(low.count(t), 3) * 0.5 for t in terms)
        )

    ranked = sorted(range(len(body)), key=lambda i: score(body[i]), reverse=True)
    chosen: set = set()
    # Reserve room for the trailing trim note and per-section join newlines
    used = len(head) + 160 + len(body)
    for i in ranked:
        if used + len(body[i]) <= budget:
            chosen.add(i)
            used += len(body[i])
    if not chosen and body:
        room = budget - used - 80
        if room > 500:
            best = ranked[0]
            body[best] = body[best][:room] + "\n... [section truncated to fit model limit]"
            chosen.add(best)

    kept = [body[i] for i in sorted(chosen)]   # preserve original file order
    note = f"\n\n[Context auto-trimmed to this model's input limit: {len(kept)} of {len(body)} sections included]"
    return head + "\n" + "\n".join(kept) + note


# ── Context Transfer ─────────────────────────────────────────────────────────

class RoutingContext:
    """Carries conversation history and routing state across failovers."""
    def __init__(self, prompt: str):
        self.original_prompt = prompt
        self.intent = classify_intent(prompt)
        self.tried: List[str] = []
        self.history: List[Dict[str, str]] = []  # [{role, content}]
        # File/repo context loaded via /file or /repo — injected into EVERY provider call
        # so switching LLMs mid-session never loses the loaded project context.
        self.system_prefix: str = ""

    def add_user_message(self, content: str):
        self.history.append({"role": "user", "content": content})

    def add_assistant_message(self, provider: str, content: str):
        self.history.append({"role": "assistant", "content": content})
        logger.info(f"[context-transfer] Response stored from {provider} ({len(content)} chars)")

    def build_history_base(self) -> str:
        """History + current prompt, WITHOUT the file/repo prefix (which is
        fitted per provider in route())."""
        if not self.history:
            return self.original_prompt
        lines = []
        for msg in self.history[-6:]:  # last 3 turns max
            lines.append(f"{msg['role'].upper()}: {msg['content']}")
        lines.append(f"USER: {self.original_prompt}")
        return "\n".join(lines)

    def build_prompt_with_context(self) -> str:
        base = self.build_history_base()
        if self.system_prefix:
            return f"{self.system_prefix}\n\n---\n\n{base}"
        return base

# ── Router Engine ────────────────────────────────────────────────────────────

class RouterEngine:
    def __init__(self):
        self.providers = [
            AntigravityProvider(),   # Gemini Flash via agy CLI (priority 0)
            CerebrasProvider(),      # wafer-scale, rivals Groq speed (priority 1)
            GroqProvider(),          # LLaMA 3.3 70B, fast (priority 2)
            HermesProvider(),        # Groq + Hermes persona (priority 3)
            MistralProvider(),       # mistral-small, free, different arch (priority 3)
            ClaudeProvider(),        # claude-sonnet-4-6 (priority 3)
            OpenRouterProvider(),    # DeepSeek-R1, Qwen-32B-Coder, LLaMA-70B (priority 5)
            CopilotProvider(),       # GitHub Copilot CLI (priority 5)
            OpenAIProvider(),        # gpt-4o (priority 6)
            CodexProvider(),         # codex-mini-latest (priority 4)
            OllamaProvider(),        # local CPU fallback (priority 7)
        ]

    @property
    def providers(self) -> List[BaseProvider]:
        return self._all_providers

    @providers.setter
    def providers(self, providers: List[BaseProvider]) -> None:
        self._all_providers = providers
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
            base_prompt = f"{memory_block}\n\n{prompt}"
        else:
            base_prompt = ctx.build_history_base()

        def _prompt_for(p: BaseProvider) -> str:
            """Assemble the prompt fitted to this provider's input budget."""
            if not ctx.system_prefix:
                return base_prompt
            prefix_budget = p.max_context_chars - len(base_prompt) - 16
            prefix = shrink_context(ctx.system_prefix, prompt, prefix_budget)
            if len(prefix) < len(ctx.system_prefix):
                logger.info(
                    f"[context-fit] {p.name}: context {len(ctx.system_prefix):,} chars "
                    f"→ {len(prefix):,} (budget {p.max_context_chars:,})"
                )
            if not prefix:
                return base_prompt
            return f"{prefix}\n\n---\n\n{base_prompt}"

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
        if preferred and preferred not in self._by_name:
            known = ", ".join(sorted(self._by_name.keys()))
            logger.warning(f"[router] unknown provider '{preferred}' — valid: {known}")
            _progress(preferred, f"Unknown provider '{preferred}' — falling back to auto", failed=True)
            preferred = None

        if preferred and preferred in self._by_name:
            p = self._by_name[preferred]
            _progress(p.name, "Using preferred provider...")
            try:
                t0 = time.time()
                resp = await asyncio.wait_for(
                    p.generate(_prompt_for(p), timeout=timeout, image=image),
                    timeout=WALL_CLOCK_TIMEOUT,
                )
                ctx.add_assistant_message(p.name, resp.content)
                _fire_score(resp, t0)
                return resp
            except asyncio.TimeoutError:
                elapsed = round(time.time() - t0)
                _progress(p.name, f"Preferred timed out ({elapsed}s > {WALL_CLOCK_TIMEOUT}s) — falling back", failed=True)
                logger.warning(f"[router] preferred {preferred} wall-clock timeout after {elapsed}s")
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
                reason = health.get("reason", "unhealthy")
                _progress(p.name, f"Unhealthy: {reason}", failed=True)
                logger.warning(f"[router] skip {p.name}: {reason}")
                continue

            _progress(p.name, f"Trying [{intent}] → {p.name}...")
            try:
                t0 = time.time()
                resp = await asyncio.wait_for(
                    p.generate(_prompt_for(p), timeout=timeout, image=image),
                    timeout=WALL_CLOCK_TIMEOUT,
                )
                ctx.add_assistant_message(p.name, resp.content)
                logger.info(f"[router] success: {p.name} (intent={intent})")
                _fire_score(resp, t0)
                return resp
            except asyncio.TimeoutError:
                elapsed = round(time.time() - t0)
                msg = f"Timed out ({elapsed}s > {WALL_CLOCK_TIMEOUT}s) — switching"
                _progress(p.name, msg, failed=True)
                logger.warning(f"[router] {p.name} wall-clock timeout after {elapsed}s")
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
