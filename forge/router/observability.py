"""
Hermes Observability Layer
--------------------------
Async quality judge that runs AFTER every LLM response.
Primary judge: llama-3.3-70b-versatile via Groq (fast, strong instruction-following).
Fallback judge: local Ollama model (llama3.1:8b or nous-hermes2) — no network dependency.

Scores feed back into routing preference over time.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("forge.observability")

JUDGE_PROMPT = """You are a strict quality judge for AI responses. Evaluate the response below.

ORIGINAL PROMPT:
{prompt}

PROVIDER: {provider}
INTENT: {intent}

RESPONSE:
{response}

Rate ONLY with a JSON object (no other text):
{{
  "quality": <1-10>,
  "intent_match": <1-10>,
  "hallucination_risk": <"low"|"medium"|"high">,
  "concise": <true|false>,
  "verdict": "<one sentence>"
}}"""


@dataclass
class QualityScore:
    provider: str
    intent: str
    quality: int = 0
    intent_match: int = 0
    hallucination_risk: str = "unknown"
    concise: bool = True
    verdict: str = ""
    latency_ms: float = 0.0
    judge: str = ""
    ts: float = field(default_factory=time.time)


class HermesObservability:
    def __init__(self, log_path: str = "logs/observability.jsonl"):
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self._ollama_url = "http://localhost:11434/api/chat"
        # In-memory last N scores for routing feedback
        self._scores: list[QualityScore] = []
        self._max_scores = 200

    async def score(
        self,
        prompt: str,
        response: str,
        provider: str,
        intent: str,
        latency_ms: float = 0.0,
    ) -> Optional[QualityScore]:
        """Score a response asynchronously. Never blocks the main response path."""
        judge_input = JUDGE_PROMPT.format(
            prompt=prompt[:600],
            response=response[:800],
            provider=provider,
            intent=intent,
        )
        score = await self._judge_hermes(judge_input, provider, intent, latency_ms)
        if score is None:
            score = await self._judge_local(judge_input, provider, intent, latency_ms)
        if score:
            self._record(score)
        return score

    async def _judge_hermes(self, judge_input: str, provider: str, intent: str, latency_ms: float) -> Optional[QualityScore]:
        from forge.config.settings import settings
        key = settings.groq_api_key
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self._groq_url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": judge_input}],
                        "temperature": 0.1,
                        "max_tokens": 150,
                    },
                )
            if resp.status_code != 200:
                return None
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return self._parse(raw, provider, intent, latency_ms, judge="hermes")
        except Exception as e:
            logger.debug(f"Hermes judge failed: {e}")
            return None

    async def _judge_local(self, judge_input: str, provider: str, intent: str, latency_ms: float) -> Optional[QualityScore]:
        # Benchmarked-safe local models on Intel i7 CPU (17s / 28s)
        for model in ("llama3.1:8b", "nous-hermes2:latest"):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.post(
                        self._ollama_url,
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": judge_input}],
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                    )
                if resp.status_code != 200:
                    continue
                raw = resp.json()["message"]["content"].strip()
                return self._parse(raw, provider, intent, latency_ms, judge=f"local:{model}")
            except Exception as e:
                logger.debug(f"Local judge {model} failed: {e}")
        return None

    def _parse(self, raw: str, provider: str, intent: str, latency_ms: float, judge: str) -> Optional[QualityScore]:
        try:
            # Extract JSON block if wrapped in markdown
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return QualityScore(
                provider=provider,
                intent=intent,
                quality=int(data.get("quality", 0)),
                intent_match=int(data.get("intent_match", 0)),
                hallucination_risk=data.get("hallucination_risk", "unknown"),
                concise=bool(data.get("concise", True)),
                verdict=data.get("verdict", ""),
                latency_ms=latency_ms,
                judge=judge,
            )
        except Exception as e:
            logger.debug(f"Score parse failed: {e} | raw={raw[:100]}")
            return None

    def _record(self, score: QualityScore):
        self._scores.append(score)
        if len(self._scores) > self._max_scores:
            self._scores.pop(0)
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(asdict(score)) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write observability log: {e}")
        logger.info(
            f"[obs] {score.provider} | intent={score.intent} | "
            f"quality={score.quality}/10 | hallucination={score.hallucination_risk} | "
            f"judge={score.judge} | {score.verdict[:60]}"
        )

    def provider_avg_quality(self, provider: str, last_n: int = 20) -> float:
        """Return average quality score for a provider from recent history."""
        recent = [s for s in self._scores[-last_n:] if s.provider == provider and s.quality > 0]
        if not recent:
            return 5.0  # neutral default
        return sum(s.quality for s in recent) / len(recent)

    def summary(self) -> dict:
        providers = {}
        for s in self._scores:
            if s.provider not in providers:
                providers[s.provider] = []
            providers[s.provider].append(s.quality)
        return {p: round(sum(v) / len(v), 2) for p, v in providers.items() if v}


# Singleton
observability = HermesObservability()
