import pytest
from unittest.mock import AsyncMock, MagicMock
from forge_core.router.engine import RouterEngine, classify_intent, _normalize_mermaid_output, _sanitize_mermaid_body
from forge_core.providers.base import ProviderResponse

@pytest.mark.asyncio
async def test_router_fallback():
    # Setup mocks
    router = RouterEngine()
    
    # Mock providers
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(side_effect=ValueError("P1 Failed"))
    
    p2 = MagicMock()
    p2.name = "p2"
    p2.priority = 2
    p2.check_health = AsyncMock(return_value={"ok": True})
    p2.generate = AsyncMock(return_value=ProviderResponse("p2", "Success from P2"))
    
    router.providers = [p1, p2]
    
    response = await router.route("test prompt")
    
    assert response.provider == "p2"
    assert response.content == "Success from P2"
    p1.generate.assert_called_once()
    p2.generate.assert_called_once()

@pytest.mark.asyncio
async def test_router_preferred_model():
    router = RouterEngine()
    
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(return_value=ProviderResponse("p1", "Success from P1"))
    
    p2 = MagicMock()
    p2.name = "p2"
    p2.priority = 2
    p2.check_health = AsyncMock(return_value={"ok": True})
    p2.generate = AsyncMock(return_value=ProviderResponse("p2", "Success from P2"))
    
    router.providers = [p1, p2]
    
    # Force p2
    response = await router.route("test prompt", preferred="p2")
    
    assert response.provider == "p2"
    p1.generate.assert_not_called()
    p2.generate.assert_called_once()

@pytest.mark.asyncio
async def test_all_providers_fail():
    router = RouterEngine()
    
    p1 = MagicMock()
    p1.name = "p1"
    p1.priority = 1
    p1.check_health = AsyncMock(return_value={"ok": True})
    p1.generate = AsyncMock(side_effect=ValueError("Fail"))
    
    router.providers = [p1]
    
    with pytest.raises(ValueError, match="All providers failed"):
        await router.route("test prompt")


def test_visual_intent_classification():
    assert classify_intent("draw an architecture diagram of the gateway") == "visual"
    assert classify_intent("generate a photo of a robot") == "visual"


def test_normalize_mermaid_wraps_raw_diagram():
    raw = "graph TD\nA[Client] --> B[Gateway]\nB --> C[Router]"
    out = _normalize_mermaid_output(raw)
    assert out.startswith("```mermaid\n")
    assert "graph TD" in out


def test_normalize_mermaid_preserves_blank_lines_and_full_body():
    raw = "flowchart TD\n    User[Developer / AI Agent]\n\n    subgraph forge[forge - Terminal App]\n        CLI[cli.py Typer]\n    end"
    out = _normalize_mermaid_output(raw)
    assert out.startswith("```mermaid\n")
    assert 'User["Developer / AI Agent"]' in out
    assert 'subgraph forge["forge - Terminal App"]' in out
    assert 'CLI["cli.py Typer"]' in out
    assert out.strip().endswith("```")


def test_normalize_mermaid_extracts_fenced_block_only():
    raw = "Here is your diagram:\n\n```mermaid\nflowchart TD\nA-->B\n```\n\nExplanation."
    out = _normalize_mermaid_output(raw)
    assert out == "```mermaid\nflowchart TD\nA-->B\n```"


def test_sanitize_mermaid_splits_combined_edges():
    body = "flowchart TD\nEngine --> P1 & P2 & P3\nP1 & P2 --> LLMs"
    out = _sanitize_mermaid_body(body)
    assert "Engine --> P1" in out
    assert "Engine --> P2" in out
    assert "Engine --> P3" in out
    assert "P1 --> LLMs" in out
    assert "P2 --> LLMs" in out
    assert "P1 & P2" not in out


def test_sanitize_mermaid_quotes_labels_and_normalizes_dashes():
    body = "flowchart TD\nUser[Developer / AI Agent]\nsubgraph forge['forge — Terminal App']\nCLI[cli.py Typer]\nend"
    out = _sanitize_mermaid_body(body)
    assert 'User["Developer / AI Agent"]' in out
    assert 'subgraph forge["forge - Terminal App"]' in out
    assert 'CLI["cli.py Typer"]' in out
    assert "—" not in out


@pytest.mark.asyncio
async def test_visual_image_prompt_prefers_image_provider():
    router = RouterEngine()

    image_p = MagicMock()
    image_p.name = "openai_image"
    image_p.priority = 1
    image_p.max_context_chars = 40_000
    image_p.check_health = AsyncMock(return_value={"ok": True})
    image_p.generate = AsyncMock(return_value=ProviderResponse("openai_image", "![img](/generated/x.png)", "gpt-image-1"))

    claude_p = MagicMock()
    claude_p.name = "claude"
    claude_p.priority = 2
    claude_p.max_context_chars = 200_000
    claude_p.check_health = AsyncMock(return_value={"ok": True})
    claude_p.generate = AsyncMock(return_value=ProviderResponse("claude", "diagram text", "claude-code"))

    router.providers = [claude_p, image_p]

    response = await router.route("generate a photo of a futuristic city")
    assert response.provider == "openai_image"
    image_p.generate.assert_called_once()
    claude_p.generate.assert_not_called()


@pytest.mark.asyncio
async def test_visual_image_prompt_falls_back_to_svg_provider_on_failure():
    router = RouterEngine()

    image_p = MagicMock()
    image_p.name = "openai_image"
    image_p.priority = 1
    image_p.max_context_chars = 40_000
    image_p.check_health = AsyncMock(return_value={"ok": True})
    image_p.generate = AsyncMock(side_effect=ValueError("billing_hard_limit_reached"))

    claude_p = MagicMock()
    claude_p.name = "claude"
    claude_p.priority = 2
    claude_p.max_context_chars = 200_000
    claude_p.check_health = AsyncMock(return_value={"ok": True})
    claude_p.generate = AsyncMock(return_value=ProviderResponse("claude", "```svg\n<svg viewBox='0 0 10 10'></svg>\n```", "claude-code"))

    router.providers = [claude_p, image_p]

    response = await router.route("generate a photo of a waterfall in the hills")
    assert response.provider == "claude"
    assert response.content.startswith("```svg")
    image_p.generate.assert_called_once()
    claude_p.generate.assert_called_once()


@pytest.mark.asyncio
async def test_visual_image_prompt_overrides_incompatible_preferred_provider():
    router = RouterEngine()
    events = []

    image_p = MagicMock()
    image_p.name = "openai_image"
    image_p.priority = 1
    image_p.max_context_chars = 40_000
    image_p.check_health = AsyncMock(return_value={"ok": True})
    image_p.generate = AsyncMock(return_value=ProviderResponse("openai_image", "![img](/generated/x.png)", "gpt-image-1"))

    codex_p = MagicMock()
    codex_p.name = "codex"
    codex_p.priority = 2
    codex_p.max_context_chars = 300_000
    codex_p.check_health = AsyncMock(return_value={"ok": True})
    codex_p.generate = AsyncMock(return_value=ProviderResponse("codex", "text only", "gpt-5.1-codex-mini"))

    router.providers = [codex_p, image_p]

    def on_progress(**kwargs):
        events.append(kwargs)

    response = await router.route(
        "generate a photo of a waterfall in the hills",
        preferred="codex",
        on_progress=on_progress,
    )
    assert response.provider == "openai_image"
    image_p.generate.assert_called_once()
    codex_p.generate.assert_not_called()
    assert any(
        "trying openai_image first" in e.get("status", "").lower()
        for e in events
    )
    assert any(
        "using openai_image first" in e.get("status", "").lower()
        for e in events
    )


@pytest.mark.asyncio
async def test_visual_diagram_prompt_normalizes_mermaid():
    router = RouterEngine()

    claude_p = MagicMock()
    claude_p.name = "claude"
    claude_p.priority = 1
    claude_p.max_context_chars = 200_000
    claude_p.check_health = AsyncMock(return_value={"ok": True})
    claude_p.generate = AsyncMock(return_value=ProviderResponse("claude", "graph TD\nA-->B", "claude-code"))

    router.providers = [claude_p]
    response = await router.route("create a mermaid architecture diagram of the gateway")
    assert response.provider == "claude"
    assert response.content.startswith("```mermaid\n")
