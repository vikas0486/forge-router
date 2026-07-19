# Forge Router — Project Notes

## Structure
- `forge_core/`: embeddable engine — `router/`, `providers/` (12 active), `memory/` (FAISS+SQLite RAG), `config/`. Zero CLI/UI imports (enforced by test). `from forge_core import router, RoutingContext`
- `forge/`: CLI client — `cli.py` (Typer), `chat.py` (REPL + local-file bridge), `ui/` (Rich, preview)
- `tests/`: pytest suite (43 tests)
- `docs/ENTERPRISE-GATEWAY-EVALUATION.md`: gateway evolution architecture + roadmap

## Credentials
Single source: `/Users/vikash/Documents/Projects/credentials/.env` (never committed; repo is PUBLIC). antigravity/ollama need no keys; copilot uses CLI OAuth.

## Runtime Data
All under `~/.forge/`: `kb/` (FAISS+SQLite), `generated/` (image output), `repo-memory/`, `logs/observability.jsonl`, preview files. Absolute paths — never written to repo or CWD.

## Active Providers (priority order)
1. antigravity (`agy` CLI — Gemini Flash, no key)
2. cerebras (gpt-oss-120b — CEREBRAS_API_KEY)
3. groq (llama-3.3-70b-versatile)
4. hermes (Groq backend, Hermes persona) · mistral (mistral-small-latest, free) · claude (claude-sonnet-4-6)
5. codex (codex-mini-latest via /v1/responses)
6. openrouter (intent-routed: R1 / Qwen-coder / LLaMA-70B) · copilot (GitHub CLI)
7. openai (gpt-4o)
8. openai_image (gpt-image-1)
9. ollama (local CPU: llama3.1:8b, qwen2.5-coder:7b, nous-hermes2)

## Key Rules
- Wall-clock timeout: 60s per provider — router switches on breach regardless of intent timeout
- Ollama is CPU-only (Intel Mac) — only the 3 benchmarked models above; qwen3/deepseek-r1/27B+ excluded
- Quality judge: Groq llama-3.3-70b primary, llama3.1:8b local fallback
- KB fact extraction: Groq llama-3.1-8b-instant primary, local llama3.1:8b fallback
- Gemini and Sakana providers removed (antigravity replaces Gemini; Sakana has no free tier)

## Key Features
- Local-file bridge: any real file/dir path typed in a chat prompt is auto-read locally and injected into context — cloud LLMs (Groq etc.) "see" local files through forge (`_auto_load_paths` in chat.py)
- Adaptive context fitting: each provider has `max_context_chars` (groq/hermes 32K, ollama 6K, claude 400K...); router relevance-trims file/repo context per provider (`shrink_context` in engine.py) — fixes Groq free-tier TPM 413s on big /repo loads
- Visual routing: `visual` intent separates image/photo prompts from diagram prompts; image prompts prefer `openai_image`, diagrams prefer `claude`/`codex`/`openai`
- Preview: auto-opens for diagrams/media, has a `Copy` button, renders Mermaid directly, Graphviz via Viz.js, PlantUML/D2 via Kroki, and serves generated images from `~/.forge/generated/`

## Status
v0.5.1 — Phase 1 gateway MVP plus visual stack upgrades. `forge_core` extracted (gateway-ready engine). `forge_gateway/`: FastAPI Anthropic-compatible `POST /v1/messages` (non-streaming) + virtual keys (SHA-256, per-key model allow-lists) + usage metering to `~/.forge/gateway.db`. Added `visual` intent, `openai_image` (`gpt-image-1`) provider, Mermaid normalization/sanitization, and richer preview rendering/copy support. 43 tests passing.
Next: streaming (SSE), `/v1/chat/completions` (OpenAI), `/v1/models`, real token counts.
