"""Adaptive context fitting — per-provider input budgets."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from forge_core.router.engine import RouterEngine, RoutingContext, shrink_context
from forge_core.providers.base import ProviderResponse


def _make_prefix():
    relevant = "### File: `auth/login.py`\n```python\ndef login(): authenticate_user()\n```" + " login" * 800
    irrelevant = "### File: `styles/theme.css`\n```css\nbody { color: red }\n```" + " padding" * 800
    return "## Project Context\n" + irrelevant + "\n" + relevant


def test_shrink_noop_when_fits():
    prefix = _make_prefix()
    assert shrink_context(prefix, "anything", len(prefix) + 10) == prefix


def test_shrink_keeps_relevant_section():
    prefix = _make_prefix()
    out = shrink_context(prefix, "fix the login authenticate bug", len(prefix) // 2)
    assert len(out) <= len(prefix) // 2 + 200
    assert "auth/login.py" in out
    assert "theme.css" not in out
    assert "auto-trimmed" in out


def test_shrink_tiny_budget_returns_empty():
    assert shrink_context(_make_prefix(), "q", 100) == ""


@pytest.mark.asyncio
async def test_router_fits_prompt_per_provider():
    """A tight-budget provider gets a trimmed prompt; a big one gets it all."""
    router = RouterEngine()
    seen = {}

    def make(name, priority, budget):
        p = MagicMock()
        p.name = name
        p.priority = priority
        p.max_context_chars = budget
        p.check_health = AsyncMock(return_value={"ok": True})
        async def gen(prompt, timeout=30, image=None, _n=name):
            seen[_n] = len(prompt)
            if _n == "small":
                raise ValueError("simulated 413")
            return ProviderResponse(_n, "ok")
        p.generate = gen
        return p

    router.providers = [make("small", 1, 3_000), make("big", 2, 500_000)]
    ctx = RoutingContext("explain the login flow")
    ctx.system_prefix = _make_prefix()

    resp = await router.route("explain the login flow", context=ctx)
    assert resp.provider == "big"
    assert seen["small"] <= 3_000
    assert seen["big"] > seen["small"]
    assert seen["big"] >= len(ctx.system_prefix)
