---
name: forge-router
description: Use this skill when the user is working in /Users/vikash/Documents/Projects/forge-router, mentions forge or forge-router, or asks about the router, providers, CLI chat flow, preview window, knowledge base, or gateway. It gives the stable project map, key invariants, and the safest files to inspect first.
---

# Forge Router

## Use this skill for

- Any task inside `/Users/vikash/Documents/Projects/forge-router`
- Questions about `forge`, `forge_router`, the multi-provider router, provider fallback, the REPL, preview, RAG memory, or the gateway
- Changes to routing behavior, provider adapters, CLI commands, repo-loading behavior, or gateway endpoints

## Project shape

Forge Router is split into three layers:

- `forge_core/`: reusable engine only. Router, providers, memory, config. This layer must stay free of CLI/UI imports.
- `forge/`: terminal app. Typer CLI, REPL, preview integration, local-file bridge, `/write`, `/run`.
- `forge_gateway/`: FastAPI gateway that exposes the router over HTTP with virtual keys and usage metering.

Read these entrypoints first:

- `forge/cli.py`: top-level commands and gateway subcommands
- `forge/chat.py`: interactive UX, file/repo loading, preview, write/run loop
- `forge_core/router/engine.py`: intent classification, provider ordering, timeout and fallback logic
- `forge_core/config/settings.py`: credential loading and runtime defaults
- `forge_core/memory/knowledge_base.py`: FAISS + SQLite memory layer
- `forge_gateway/app.py`: HTTP surface for the gateway MVP

## Core behavior

### CLI and chat

- Running `forge` enters the REPL by default.
- `forge ask` is the one-shot path.
- `forge status` and `forge doctor` diagnose providers.
- `forge gateway ...` manages the gateway server and virtual keys.

Inside chat, the key commands are:

- `/file <path>`: load a file into persistent session context
- `/repo <path>`: load a repository tree and source contents into persistent session context
- `/write <path>`: save the last response, preferring the largest fenced code block
- `/run <command>`: execute a shell command and inject its output back into chat history
- `/model <name|auto>`: pin or unpin a provider
- `/p` or `/preview`: toggle the preview window

### Routing

The router classifies prompts with regex into:

- `chat`
- `summarization`
- `code`
- `reasoning`
- `agentic`

Important invariants:

- Provider selection is intent-ordered, not random.
- Every provider call is wrapped in a hard 60 second wall-clock timeout.
- Unhealthy providers are skipped before generation.
- Preferred providers are tried first, then normal fallback resumes.

### Context transfer

There are three context layers:

- `RoutingContext.history`: recent conversational turns
- `RoutingContext.system_prefix`: loaded file/repo context that must survive failover
- Knowledge-base retrieval: relevant memories from prior interactions

Do not break the separation between `history` and `system_prefix`. That split is what keeps loaded repo context intact when the router switches providers.

### Adaptive context fitting

Large repo context is trimmed per provider budget. The router does not send one universal prompt to all providers. It scores `###` sections for relevance and keeps the best ones that fit the target provider's `max_context_chars`.

This is a core design feature, not an optimization detail. Changes here can affect correctness for large `/repo` sessions and low-budget providers.

## Memory and persistence

- Runtime data lives under `~/.forge/`, not inside the repo.
- The knowledge base stores interactions and memories in SQLite and indexes embeddings in FAISS.
- Embeddings come from Ollama `nomic-embed-text`.
- Retrieval is skipped when the index is empty.
- Consolidation runs asynchronously after enough interactions and extracts reusable facts from recent history.

When working on memory behavior, inspect:

- `forge_core/memory/embedder.py`
- `forge_core/memory/knowledge_base.py`

## Preview

The preview is a local HTTP server plus a macOS webview window.

- It opens automatically for visual output such as Mermaid or images.
- It can also open from visual intent in the user prompt.
- Plain text should not overwrite a stale preview window unless the interaction is explicitly visual.

Preview-related files:

- `forge/ui/preview_server.py`
- `forge/ui/preview_window.py`
- `forge/chat.py`

## Gateway

The current gateway is the Phase 1 wedge, not a full control plane.

What exists now:

- `POST /v1/messages`
- `GET /health`
- Virtual keys stored hashed in SQLite
- Per-key usage metering with estimated token counts

What the codebase signals but the app does not fully implement yet:

- OpenAI-compatible chat completions
- Model discovery endpoints
- Streaming responses

When touching gateway code, keep the current truth in code above aspirational doc claims.

## Credentials and environment

- Shared credentials load from `/Users/vikash/Documents/Projects/credentials/.env`, then local `.env` fills any gaps.
- `settings.py` deliberately lets the shared credentials file override inherited shell values.
- Some providers depend on API keys, others on local CLIs or local Ollama.

Do not hardcode secrets, machine-local tokens, or session-specific auth state into code or skill text.

## Working rules for this repo

- Preserve the `forge_core` boundary. It must remain importable without pulling in `forge` UI/CLI modules.
- Prefer reading implementation over trusting docs when they disagree.
- Treat README and project notes as helpful but possibly stale on versions and roadmap endpoints.
- Keep runtime artifacts out of the repo. This project intentionally writes operational state to `~/.forge/`.
- Be careful with `chat.py`: it mixes UX, local file loading, subprocess execution, preview behavior, and session state.

## Test map

Use the targeted tests that match the area you changed:

- `tests/test_router.py`: fallback and preferred-provider routing
- `tests/test_context_fit.py`: adaptive context fitting
- `tests/test_gateway.py`: gateway auth, metering, endpoint behavior
- `tests/test_forge_core.py`: `forge_core` public API and import boundary
- `tests/test_cli.py`, `tests/test_ux.py`: CLI and chat UX behavior
- `tests/test_codex_provider.py`: Codex adapter behavior

Typical validation command:

```bash
uv run pytest tests -q
```

If you changed only one area, prefer the narrowest relevant test file first.

## Recommended read order

For architecture questions:

1. `README.md`
2. `forge/cli.py`
3. `forge_core/router/engine.py`
4. `forge/chat.py`

For gateway work:

1. `forge_gateway/app.py`
2. `forge_gateway/store.py`
3. `docs/ENTERPRISE-GATEWAY-EVALUATION.md`

For memory work:

1. `forge_core/memory/knowledge_base.py`
2. `forge_core/memory/embedder.py`
3. `tests/test_context_fit.py`

## Avoid copying from the old Claude skill

Do not rely on machine-specific live state from older notes, such as:

- current provider quota status
- live auth state for Claude, Copilot, or Antigravity
- personal shell aliases
- temporary benchmark claims unless you re-verify them in code or tests

This skill should stay stable and useful even when credentials, quotas, or installed CLIs change.
