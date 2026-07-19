"""Virtual keys + usage metering — SQLite at ~/.forge/gateway.db.

Keys are stored as SHA-256 hashes; the plaintext fk-... key is shown exactly
once at creation. An in-process cache keeps the auth check off the hot path.
(SQLite is the zero-budget MVP store; the schema maps 1:1 onto Postgres for
the multi-user phase.)
"""
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path.home() / ".forge" / "gateway.db"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class GatewayStore:
    def __init__(self, db_path: Optional[Path] = None):
        path = db_path or DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._auth_cache: Dict[str, Dict[str, Any]] = {}
        self._init()

    def _init(self):
        with self._lock:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    key_prefix TEXT NOT NULL,
                    allowed_models TEXT,          -- JSON list or NULL = all
                    disabled INTEGER DEFAULT 0,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    key_name TEXT,
                    endpoint TEXT,
                    model_requested TEXT,
                    provider TEXT,
                    model_used TEXT,
                    intent TEXT,
                    est_prompt_tokens INTEGER,
                    est_completion_tokens INTEGER,
                    latency_ms REAL,
                    status TEXT
                );
            """)
            self._db.commit()

    # ── Keys ────────────────────────────────────────────────────────────────

    def create_key(self, name: str, allowed_models: Optional[List[str]] = None) -> str:
        key = "fk-" + secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute(
                "INSERT INTO keys (name, key_hash, key_prefix, allowed_models, created_at) VALUES (?,?,?,?,?)",
                (name, _hash(key), key[:11], json.dumps(allowed_models) if allowed_models else None, time.time()),
            )
            self._db.commit()
        return key  # plaintext returned once, never stored

    def verify(self, key: str) -> Optional[Dict[str, Any]]:
        h = _hash(key)
        if h in self._auth_cache:
            return self._auth_cache[h]
        with self._lock:
            row = self._db.execute(
                "SELECT name, allowed_models, disabled FROM keys WHERE key_hash=?", (h,)
            ).fetchone()
        if not row or row[2]:
            return None
        identity = {"name": row[0], "allowed_models": json.loads(row[1]) if row[1] else None}
        self._auth_cache[h] = identity
        return identity

    def list_keys(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT name, key_prefix, allowed_models, disabled, created_at FROM keys ORDER BY id"
            ).fetchall()
        return [
            {"name": n, "prefix": p, "allowed_models": json.loads(a) if a else None,
             "disabled": bool(d), "created_at": c}
            for n, p, a, d, c in rows
        ]

    def revoke(self, name: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE keys SET disabled=1 WHERE name=?", (name,))
            self._db.commit()
        self._auth_cache.clear()   # force re-verify on next request
        return cur.rowcount > 0

    # ── Usage ───────────────────────────────────────────────────────────────

    def record_usage(self, **row: Any):
        with self._lock:
            self._db.execute(
                "INSERT INTO usage (ts, key_name, endpoint, model_requested, provider, model_used,"
                " intent, est_prompt_tokens, est_completion_tokens, latency_ms, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), row.get("key_name"), row.get("endpoint"), row.get("model_requested"),
                 row.get("provider"), row.get("model_used"), row.get("intent"),
                 row.get("est_prompt_tokens", 0), row.get("est_completion_tokens", 0),
                 row.get("latency_ms", 0.0), row.get("status", "ok")),
            )
            self._db.commit()

    def top(self, days: int = 7) -> List[Dict[str, Any]]:
        since = time.time() - days * 86400
        with self._lock:
            rows = self._db.execute(
                "SELECT key_name, COUNT(*), SUM(est_prompt_tokens), SUM(est_completion_tokens),"
                " ROUND(AVG(latency_ms),1), SUM(status='ok')"
                " FROM usage WHERE ts>=? GROUP BY key_name ORDER BY 2 DESC", (since,)
            ).fetchall()
        return [
            {"key_name": k, "requests": r, "prompt_tokens": pt or 0, "completion_tokens": ct or 0,
             "avg_latency_ms": lat or 0, "ok": ok or 0}
            for k, r, pt, ct, lat, ok in rows
        ]
