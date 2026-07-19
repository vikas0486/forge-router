"""Best-effort token compression for gateway traffic.

Uses headroom's `SmartCrusher.crush()` DIRECTLY, bypassing the high-level
`headroom.compress()` pipeline — that pipeline routes content through magika
(an ML content-type detector) which needs onnxruntime, and onnxruntime has no
Intel-mac / py3.14 wheel. Without it the pipeline degrades to `router:noop`
(zero savings). Calling the crusher directly still compresses large repeated
JSON / tabular blocks into a schema + rows representation.

Compression here is a *bonus*, never load-bearing: every path degrades to the
original text if the crusher is unavailable or fails to shrink the block.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("forge_gateway.compress")

# Only attempt to crush blocks at least this large — small prose blocks can
# come back LONGER from schema extraction, so tiny inputs aren't worth it.
_MIN_CHARS = 800

try:
    from headroom import SmartCrusher

    _crusher: Optional["SmartCrusher"] = SmartCrusher()
    logger.info("headroom SmartCrusher available — gateway compression enabled")
except Exception as e:  # pragma: no cover - depends on optional dep state
    _crusher = None
    logger.warning("headroom SmartCrusher unavailable (%s) — compression disabled", e)


def crush_text(text: str) -> str:
    """Return a compressed form of `text`, or `text` unchanged if compression
    is unavailable, errors, or fails to actually shrink the block."""
    if _crusher is None or not text or len(text) < _MIN_CHARS:
        return text
    try:
        result = _crusher.crush(text)
        compressed = getattr(result, "compressed", None)
        if isinstance(compressed, str) and len(compressed) < len(text):
            return compressed
    except Exception as e:  # crusher is Rust-backed; never let it break a request
        logger.debug("crush failed, using original text: %s", e)
    return text


def compression_available() -> bool:
    return _crusher is not None
