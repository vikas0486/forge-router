"""forge-gateway FastAPI app — Phase 1 wedge.

Exposes an Anthropic-compatible `POST /v1/messages` so that Claude Code (and any
Anthropic-SDK client) can be pointed at Forge with:

    ANTHROPIC_BASE_URL=http://localhost:8080  ANTHROPIC_API_KEY=fk-...  claude

Each request is: authenticated (virtual key) → its large text blocks crushed →
routed through forge_core's intent router to the cheapest healthy provider →
translated back into the Anthropic Messages response shape → metered per key.

Note: this routes to Forge's provider chain (Groq/Cerebras/Ollama/...), NOT to
Anthropic. Responses come from whichever provider the router picks, so answer
quality follows Forge's routing, not Claude. This is the deliberate zero-cost
design chosen for the gateway MVP.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from forge_core import router
from forge_gateway.compress import compression_available, crush_text
from forge_gateway.store import GatewayStore

logger = logging.getLogger("forge_gateway.app")

# ~4 chars/token — the gateway meters ESTIMATES (no provider usage frames in the
# MVP). Documented as an estimate in every usage row.
_CHARS_PER_TOKEN = 4


def _est_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _text_from_content(content: Any) -> str:
    """Anthropic message `content` is either a string or a list of blocks
    ({"type":"text","text":...}, tool_use, tool_result, ...). Flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                parts.append(_text_from_content(block.get("content", "")))
            elif block.get("type") == "tool_use":
                parts.append(f"[tool_use {block.get('name','')}: {block.get('input','')}]")
        return "\n".join(parts)
    return ""


def _flatten_messages(system: Any, messages: List[Dict[str, Any]]) -> str:
    """Collapse an Anthropic system + messages array into a single prompt for
    the router, crushing each large block on the way."""
    lines: List[str] = []
    if system:
        sys_text = _text_from_content(system)
        if sys_text.strip():
            lines.append(f"SYSTEM: {crush_text(sys_text)}")
    for msg in messages:
        role = str(msg.get("role", "user")).upper()
        text = _text_from_content(msg.get("content", ""))
        if text.strip():
            lines.append(f"{role}: {crush_text(text)}")
    return "\n\n".join(lines)


def create_app(store: Optional[GatewayStore] = None) -> FastAPI:
    app = FastAPI(title="forge-gateway", version="0.1.0")
    app.state.store = store or GatewayStore()

    def get_store() -> GatewayStore:
        return app.state.store

    def require_key(
        authorization: Optional[str] = Header(None),
        x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    ) -> Dict[str, Any]:
        """Accept the virtual key from either the OpenAI-style
        `Authorization: Bearer fk-...` or Anthropic-style `x-api-key: fk-...`."""
        key = None
        if x_api_key:
            key = x_api_key
        elif authorization and authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        if not key:
            raise HTTPException(401, "missing virtual key (x-api-key or Authorization: Bearer)")
        identity = get_store().verify(key)
        if not identity:
            raise HTTPException(401, "invalid or disabled virtual key")
        return identity

    def _check_model_allowed(identity: Dict[str, Any], model: str) -> None:
        allowed = identity.get("allowed_models")
        if allowed and model not in allowed:
            raise HTTPException(
                403, f"key '{identity['name']}' is not allowed model '{model}'"
            )

    # ── health ────────────────────────────────────────────────────────────────
    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "compression": compression_available()}

    # ── Anthropic-compatible messages endpoint ──────────────────────────────────
    @app.post("/v1/messages")
    async def messages(request: Request, identity: Dict[str, Any] = Depends(require_key)):
        body = await request.json()
        model = str(body.get("model", "forge/auto"))
        _check_model_allowed(identity, model)

        msgs = body.get("messages", [])
        if not isinstance(msgs, list) or not msgs:
            raise HTTPException(400, "'messages' must be a non-empty array")

        prompt = _flatten_messages(body.get("system"), msgs)

        # `forge/<name>` pins a provider; anything else (incl. real Anthropic
        # model ids from Claude Code) falls through to intent auto-routing.
        preferred = None
        if model.startswith("forge/"):
            alias = model.split("/", 1)[1]
            if alias not in ("auto", "code", "chat", "reasoning", "agentic"):
                preferred = alias

        t0 = time.time()
        ctx = router.new_context(prompt)
        try:
            resp = await router.route(prompt, preferred=preferred, context=ctx)
        except Exception as e:
            logger.warning("route failed: %s", e)
            get_store().record_usage(
                key_name=identity["name"], endpoint="/v1/messages",
                model_requested=model, provider="none", intent=ctx.intent,
                est_prompt_tokens=_est_tokens(prompt), status="error",
                latency_ms=round((time.time() - t0) * 1000, 1),
            )
            raise HTTPException(502, f"all providers failed: {e}")

        latency_ms = round((time.time() - t0) * 1000, 1)
        usage = resp.usage
        in_tok = usage.input_tokens if usage else _est_tokens(prompt)
        out_tok = usage.output_tokens if usage else _est_tokens(resp.content)
        get_store().record_usage(
            key_name=identity["name"], endpoint="/v1/messages",
            model_requested=model, provider=resp.provider, model_used=resp.model,
            intent=ctx.intent, est_prompt_tokens=in_tok, est_completion_tokens=out_tok,
            latency_ms=latency_ms, status="ok",
        )

        # Anthropic Messages response shape
        return JSONResponse({
            "id": f"msg_forge_{int(t0*1000)}",
            "type": "message",
            "role": "assistant",
            "model": resp.model or f"forge:{resp.provider}",
            "content": [{"type": "text", "text": resp.content}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
            # non-standard, but handy for debugging which provider answered:
            "forge_provider": resp.provider,
        })

    return app
