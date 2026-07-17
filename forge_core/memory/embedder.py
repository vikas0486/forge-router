"""Embedding engine using nomic-embed-text via Ollama."""
import httpx
import logging
import numpy as np

logger = logging.getLogger("forge_core.memory.embedder")

EMBED_MODEL = "nomic-embed-text:latest"
OLLAMA_URL = "http://localhost:11434/api/embeddings"


async def embed(text: str) -> np.ndarray:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text})
        r.raise_for_status()
        vec = r.json()["embedding"]
        return np.array(vec, dtype=np.float32)
