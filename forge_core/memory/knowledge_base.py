"""
Forge Knowledge Base — FAISS-backed vector store with SQLite metadata.

Lifecycle:
  - Every interaction is logged.
  - After MEMORY_TRIGGER_PCT % of session interactions, the KB auto-consolidates:
      extracts key facts → embeds → stores in FAISS index.
  - On each new prompt: top-K relevant memories are retrieved and injected as context.
"""
import asyncio
import httpx
import logging
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

try:
    import faiss
    import numpy as np
    _FAISS_OK = True
except ImportError:
    faiss = None  # type: ignore
    np = None     # type: ignore
    _FAISS_OK = False

from forge_core.memory.embedder import embed

logger = logging.getLogger("forge_core.memory.kb")

MEMORY_TRIGGER_PCT = 10       # consolidate every 10% of interactions
MIN_INTERACTIONS_BEFORE_KB = 5
TOP_K_RECALL = 4
EMBED_DIM = 768               # nomic-embed-text output dimension
# Fixed absolute home — a relative path here scattered memory/ dirs into
# whatever CWD forge was launched from. All forge runtime data lives in ~/.forge.
FORGE_DATA_DIR = Path.home() / ".forge"
DB_PATH = FORGE_DATA_DIR / "kb" / "forge_kb.db"
INDEX_PATH = FORGE_DATA_DIR / "kb" / "forge_kb.faiss"


@dataclass
class MemoryEntry:
    id: int
    text: str
    source: str        # "interaction" | "fact" | "routing"
    intent: str
    provider: str
    ts: float
    quality: float = 0.0


class ForgeKnowledgeBase:
    def __init__(self):
        if not _FAISS_OK:
            logger.warning("[kb] faiss not installed — KB running without vector search. "
                           "Run: pipx runpip forge-router install faiss-cpu")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()
        self._index = None  # type: ignore
        self._index_ids: List[int] = []   # maps FAISS position → DB row id
        self._load_index()
        self._interaction_count = 0
        self._consolidation_count = 0

    def _init_db(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT,
                response TEXT,
                provider TEXT,
                intent TEXT,
                quality REAL,
                ts REAL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT UNIQUE,
                source TEXT,
                intent TEXT,
                provider TEXT,
                quality REAL,
                ts REAL,
                embedding BLOB
            );
        """)
        self._db.commit()

    def _load_index(self):
        if not _FAISS_OK:
            return
        rows = self._db.execute(
            "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL ORDER BY id"
        ).fetchall()
        if not rows:
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._index_ids = []
            return
        vecs = []
        ids = []
        for row_id, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            if vec.shape[0] == EMBED_DIM:
                vecs.append(vec)
                ids.append(row_id)
        if vecs:
            matrix = np.stack(vecs)
            faiss.normalize_L2(matrix)
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._index.add(matrix)
            self._index_ids = ids
        else:
            self._index = faiss.IndexFlatIP(EMBED_DIM)
            self._index_ids = []
        logger.info(f"[kb] Loaded {len(self._index_ids)} memories from disk")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def record_interaction(self, prompt: str, response: str, provider: str, intent: str, quality: float = 0.0):
        """Call after every routed response."""
        self._db.execute(
            "INSERT INTO interactions (prompt, response, provider, intent, quality, ts) VALUES (?,?,?,?,?,?)",
            (prompt[:2000], response[:4000], provider, intent, quality, time.time()),
        )
        self._db.commit()
        self._interaction_count += 1

        # Trigger consolidation every MEMORY_TRIGGER_PCT % of interactions
        trigger_every = max(MIN_INTERACTIONS_BEFORE_KB, MEMORY_TRIGGER_PCT)
        if self._interaction_count % trigger_every == 0:
            asyncio.ensure_future(self._consolidate())

    async def retrieve(self, prompt: str, top_k: int = TOP_K_RECALL) -> List[str]:
        """Retrieve top-K relevant memories for the given prompt."""
        if self._index is None or self._index.ntotal == 0:
            return []
        try:
            q_vec = await embed(prompt)
            q_vec = q_vec.reshape(1, -1)
            faiss.normalize_L2(q_vec)
            scores, indices = self._index.search(q_vec, min(top_k, self._index.ntotal))
            memories = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or score < 0.55:   # similarity threshold
                    continue
                row_id = self._index_ids[idx]
                row = self._db.execute("SELECT text FROM memories WHERE id=?", (row_id,)).fetchone()
                if row:
                    memories.append(row[0])
            return memories
        except Exception as e:
            logger.warning(f"[kb] retrieve failed: {e}")
            return []

    def build_context_block(self, memories: List[str]) -> str:
        """Format retrieved memories into a context block for prompt injection."""
        if not memories:
            return ""
        lines = ["[FORGE MEMORY — relevant context from past interactions]"]
        for i, m in enumerate(memories, 1):
            lines.append(f"{i}. {m}")
        lines.append("[END MEMORY]")
        return "\n".join(lines)

    def stats(self) -> dict:
        total_interactions = self._db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        total_memories = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return {
            "total_interactions": total_interactions,
            "total_memories": total_memories,
            "index_size": self._index.ntotal if self._index else 0,
            "consolidations_run": self._consolidation_count,
            "trigger_every_n": max(MIN_INTERACTIONS_BEFORE_KB, MEMORY_TRIGGER_PCT),
        }

    # ── Consolidation ───────────────────────────────────────────────────────────

    async def _consolidate(self):
        """Extract facts from recent interactions and embed them into the FAISS index."""
        self._consolidation_count += 1
        logger.info(f"[kb] Consolidation #{self._consolidation_count} triggered")

        # Pull last 20 interactions not yet consolidated
        rows = self._db.execute(
            "SELECT prompt, response, provider, intent, quality FROM interactions "
            "ORDER BY id DESC LIMIT 20"
        ).fetchall()
        if not rows:
            return

        # Extract facts using a fast local model
        facts = await self._extract_facts(rows)
        added = 0
        for fact, source_intent, source_provider, quality in facts:
            if not fact.strip():
                continue
            # Deduplicate
            exists = self._db.execute("SELECT id FROM memories WHERE text=?", (fact,)).fetchone()
            if exists:
                continue
            try:
                vec = await embed(fact)
                if vec.shape[0] != EMBED_DIM:
                    continue
                blob = vec.tobytes()
                cur = self._db.execute(
                    "INSERT INTO memories (text, source, intent, provider, quality, ts, embedding) VALUES (?,?,?,?,?,?,?)",
                    (fact, "fact", source_intent, source_provider, quality, time.time(), blob),
                )
                self._db.commit()

                # Add to FAISS
                norm_vec = vec.reshape(1, -1)
                faiss.normalize_L2(norm_vec)
                self._index.add(norm_vec)
                self._index_ids.append(cur.lastrowid)
                added += 1
            except Exception as e:
                logger.warning(f"[kb] embed/store failed for fact: {e}")

        # Persist FAISS index
        if added > 0:
            faiss.write_index(self._index, str(INDEX_PATH))
            logger.info(f"[kb] Added {added} new memories. Total: {self._index.ntotal}")

    async def _extract_facts(self, rows) -> List[tuple]:
        """Use local qwen3 or groq to extract key facts from interaction history."""
        combined = []
        for prompt, response, provider, intent, quality in rows[:10]:
            combined.append(f"Q: {prompt[:200]}\nA: {response[:300]}")
        text_block = "\n---\n".join(combined)

        extract_prompt = f"""Extract 3-5 concise factual statements from these AI interactions that would be useful to remember for future conversations. Each fact on a new line starting with "FACT:". Only extract genuinely useful, reusable facts.

{text_block}

Facts:"""

        # Try groq first (fast), then local
        fact_text = await self._call_fast_llm(extract_prompt)
        if not fact_text:
            return []

        facts = []
        for line in fact_text.split("\n"):
            line = line.strip()
            if line.startswith("FACT:"):
                fact = line[5:].strip()
                if len(fact) > 10:
                    # Use the first row's metadata as representative
                    facts.append((fact, rows[0][3], rows[0][2], rows[0][4] or 5.0))
        return facts

    async def _call_fast_llm(self, prompt: str) -> Optional[str]:
        from forge_core.config.settings import settings
        # Prefer Groq (fast) for extraction
        if settings.groq_api_key:
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        json={
                            "model": "llama-3.1-8b-instant",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 300,
                            "temperature": 0.3,
                        },
                    )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.debug(f"[kb] Groq extraction failed: {e}")

        # Fallback to fastest benchmarked local model (llama3.1:8b — 17s on Intel i7)
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "llama3.1:8b",
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 300},
                    },
                )
            if r.status_code == 200:
                return r.json()["message"]["content"]
        except Exception as e:
            logger.debug(f"[kb] Local extraction failed: {e}")
        return None


# Singleton
knowledge_base = ForgeKnowledgeBase()
