"""
forge-core — the embeddable routing engine behind Forge.

Zero CLI/UI imports: this package contains only the router, providers,
memory (RAG), and config layers, so any host — the forge CLI today, the
forge-gateway HTTP service in Phase 1 — can drive the same engine.

Usage:
    from forge_core import router, RoutingContext
    response = await router.route("prompt", context=router.new_context("prompt"))
"""
from forge_core.config.settings import settings
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.router.engine import (
    RouterEngine,
    RoutingContext,
    classify_intent,
    router,
)
from forge_core.router.observability import observability
from forge_core.memory.knowledge_base import knowledge_base

__all__ = [
    "settings",
    "BaseProvider",
    "ProviderResponse",
    "RouterEngine",
    "RoutingContext",
    "classify_intent",
    "router",
    "observability",
    "knowledge_base",
]
