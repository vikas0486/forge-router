# Forge Router — Project Notes

## Structure
- `forge/`: main package — `cli.py` (Typer), `chat.py` (REPL), `router/`, `providers/` (11 active), `memory/` (FAISS+SQLite RAG), `ui/` (Rich, preview), `config/`
- `tests/`: pytest suite (16 tests)
- `docs/ENTERPRISE-GATEWAY-EVALUATION.md`: gateway evolution architecture + roadmap

## Credentials
Single source: `/Users/vikash/Documents/Projects/credentials/.env` (never committed; repo is PUBLIC)

## Active Providers (priority order)
1. antigravity (`agy` CLI — Gemini Flash, no key)
2. cerebras (gpt-oss-120b — CEREBRAS_API_KEY)
3. groq (llama-3.3-70b-versatile)
4. hermes (Groq backend, Hermes persona) · mistral (mistral-small-latest, free) · claude (claude-sonnet-4-6)
5. codex (codex-mini-latest via /v1/responses)
6. openrouter (intent-routed: R1 / Qwen-coder / LLaMA-70B) · copilot (GitHub CLI)
7. openai (gpt-4o)
8. ollama (local CPU: llama3.1:8b, qwen2.5-coder:7b, nous-hermes2)

## Key Rules
- Wall-clock timeout: 60s per provider — router switches on breach regardless of intent timeout
- Ollama is CPU-only (Intel Mac) — only the 3 benchmarked models above; qwen3/deepseek-r1/27B+ excluded
- Quality judge: Groq llama-3.3-70b primary, llama3.1:8b local fallback
- KB fact extraction: Groq llama-3.1-8b-instant primary, local llama3.1:8b fallback
- Gemini and Sakana providers removed (antigravity replaces Gemini; Sakana has no free tier)

## Status
v0.2.0 tagged — last CLI-only release. Next: Phase 0 gateway extraction (`forge-core`).
