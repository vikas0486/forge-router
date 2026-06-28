"""Embedding engine using nomic-embed-text via Ollama."""
import httpx
import logging
import numpy as np
from typing import List

logger = logging.getLogger("forge.memory.embedder")

EMBED_MODEL = "nomic-embed-text:latest"
OLLAMA_URL = "http://localhost:11434/api/embeddings"


async def embed(text: str) -> np.ndarray:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text})
        r.raise_for_status()
        vec = r.json()["embedding"]
        return np.array(vec, dtype=np.float32)


async def embed_batch(texts: List[str]) -> List[np.ndarray]:
    results = []
    for t in texts:
        results.append(await embed(t))
    return results


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
