"""
forge-gateway — Phase 1 of the Forge enterprise AI gateway.

A FastAPI service that exposes the forge_core routing engine over the two
protocols AI clients already speak:

    POST /v1/messages          (Anthropic-compatible — Claude Code via ANTHROPIC_BASE_URL)
    POST /v1/chat/completions  (OpenAI-compatible — Cursor, SDKs, LangChain)
    GET  /v1/models            (model discovery, filtered per virtual key)

Clients authenticate with forge virtual keys (fk-...); real provider keys never
leave the gateway. Every request is metered per key into ~/.forge/gateway.db.
"""
__all__ = ["create_app"]

from forge_gateway.app import create_app
