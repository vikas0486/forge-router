---
name: forge-router
description: Guides the agent on the architecture, development, testing, and maintenance of the forge-router multi-LLM gateway.
---

# ⚒️ Forge Router Developer Skill

This skill defines the development workflows, architectural constraints, and capabilities of the **Forge Router** project. It is automatically loaded by Antigravity agents when working in this workspace.

## 1. Flagship Vision & Core Strategy
The objective of **Forge Router** is to build a terminal-first co-pilot that routes prompts across multiple LLM providers, optimizing for free tokens, latency, and capability.
*   **Prompt Intent Classification**: The router classifies the user prompt in under 1ms and dynamically selects the best provider chain.
*   **Resiliency & Failovers**: If a provider fails (e.g., rate limits, API timeouts, credentials expired), the engine falls back to the next healthy provider in the chain, maintaining multi-turn context.
*   **No-Cost Optimization**: Leverages local providers (Ollama), free tiers (Mistral-small, Cerebras), and OAuth CLI binaries (Antigravity/agy) to minimize run costs.

---

## 2. Core Architecture & Project Layout

Since v0.3.0 the engine lives in `forge_core` — an embeddable package with zero CLI/UI imports (enforced by `tests/test_forge_core.py`); `forge/` is the CLI client.

```
forge_core/
├── router/
│   ├── engine.py           # RouterEngine, RoutingContext, intent classifier, shrink_context, deep_probe
│   └── observability.py    # Quality and latency scoring per provider
├── providers/              # 11 provider adapters (extending BaseProvider)
│   ├── base.py             # Abstract BaseProvider and ProviderResponse class
│   ├── antigravity.py      # Antigravity (agy CLI — Priority 0 Gemini Flash)
│   ├── cerebras.py         # Cerebras wafer-scale fast inference API
│   ├── groq.py             # Groq LLaMA 3.3 API
│   ├── hermes.py           # Hermes logic
│   ├── mistral.py          # Mistral Small free tier API
│   ├── claude.py           # Anthropic Claude API
│   ├── openrouter.py       # OpenRouter model aggregator
│   ├── copilot.py          # GitHub Copilot CLI wrapper
│   ├── openai.py           # OpenAI GPT-4o API
│   ├── codex.py            # Codex Responses API
│   └── ollama.py           # Local Ollama fallback
├── memory/
│   ├── knowledge_base.py   # FAISS Index + SQLite DB interaction recorder (data in ~/.forge/kb/)
│   └── embedder.py         # Ollama nomic-embed-text wrapper
└── config/
    └── settings.py         # pydantic-settings; credentials/.env OVERRIDES shell env

forge/
├── cli.py                  # Typer CLI (status, doctor [--live], ask, chat)
├── chat.py                 # ForgeChat REPL (local-file bridge, preview, /write /run)
├── ui/
│   ├── console.py          # Rich terminal layouts and spinners
│   ├── preview_server.py   # HTTP server state for live preview
│   └── preview_window.py   # pywebview WKWebView subprocess
```

---

## 3. Google Antigravity Integration
*   **Adapter File**: [forge/providers/antigravity.py](file:///Users/vikash/Documents/Projects/forge-router/forge/providers/antigravity.py)
*   **Priority**: Priority 0 (primary provider for chat and default routing).
*   **Execution Model**: Executes `agy --print "<prompt>"` asynchronously using `asyncio.create_subprocess_exec` so it does not block the Python runtime.
*   **Auth Requirement**: Requires **no static API keys** in the `.env` file since it leverages local system OAuth configurations.

---

## 4. Intent Routing Table
The [engine.py](file:///Users/vikash/Documents/Projects/forge-router/forge/router/engine.py) file parses prompts via regex to determine the category. If a provider fails, the engine falls back in the following sequence:

| Intent | Detection Regex keywords | Preferred Routing Chain |
| :--- | :--- | :--- |
| **`chat`** | Default | `groq` → `cerebras` → `antigravity` → `claude` → `mistral` → `openai` → `hermes` → `openrouter` → `ollama` |
| **`summarization`**| `summarize`, `tldr`, `condense` | `antigravity` → `groq` → `cerebras` → `claude` → `mistral` → `openrouter` → `openai` → `ollama` |
| **`code`** | `code`, `function`, `debug`, `error`, `bug` | `codex` → `claude` → `hermes` → `openrouter` → `mistral` → `openai` → `groq` → `cerebras` → `ollama` |
| **`reasoning`** | `reason`, `think`, `analyze`, `solve` | `hermes` → `claude` → `openrouter` → `mistral` → `openai` → `groq` → `cerebras` → `antigravity` → `ollama` |
| **`agentic`** | `search`, `plan`, `execute`, `automate` | `claude` → `openai` → `hermes` → `openrouter` → `groq` → `cerebras` → `mistral` → `antigravity` → `ollama` |

*   **Wall-Clock Timeout**: Enforces a strict `60s` limit per provider, switching immediately upon breach.
*   **Adaptive Context Fitting**: every provider declares `max_context_chars`; `route()` relevance-trims file/repo context per provider (groq 24K … claude 200K), so tight free tiers work with huge `/repo` loads.
*   **Local-File Bridge**: real file/dir paths typed in a chat prompt are auto-read locally and injected into context — cloud LLMs read local files through forge.
*   **Deep Health Probe**: `forge doctor --live` (`RouterEngine.deep_probe`) sends a real generation to all providers concurrently, classifying CONFIG / RUNTIME / TIMEOUT failures.
*   **Claude via subscription**: the `claude` provider shells out to `claude -p` (Claude Code CLI, paid subscription; scrubbed env, DEVNULL stdin, neutral cwd) — no prepaid API credits needed.
*   **Groq intent routing**: gpt-oss-120b for code/reasoning/agentic (reasoning_effort=low), llama-3.3-70b for chat/summarization.

---

## 5. RAG (Knowledge Base) Pipeline
*   **Embedding Generator**: Uses Ollama's `nomic-embed-text` locally.
*   **Vector Database**: Employs `FAISS IndexFlatIP` (cosine similarity) to index 768-dimensional vectors.
*   **SQLite Storage**: Stores full interaction histories and memories.
*   **Memory Consolidation**: Auto-consolidates memories every 10 interactions, extracting facts using LLMs to update the FAISS vector index.
*   **Cold-Start Safety**: If the FAISS index is empty, embedding operations are skipped automatically to avoid initialization overhead.

---

## 6. Live WebView Preview
*   **TUI Toggle**: `/p`, `/preview`, or `Ctrl+P`.
*   **Triggers**: Opens automatically when responses contain Mermaid diagrams, markdown tables, or images.
*   **Mechanism**: Runs a python webview subprocess rendering a local HTTP server state (port `7654`) with 800ms polling.

---

## 7. Developer & Maintenance Workflows

### Environment Diagnostics
```bash
# Verify API keys, system dependencies, and env variables
forge doctor

# Check health and response status of all active model providers
forge status
```

### Running the Interface
```bash
# Launch interactive TUI session with auto-routing
forge chat

# Launch session locking preferred model (e.g. groq)
forge chat --model groq
```

### Running Tests
All tests are implemented in the `tests/` directory:
```bash
pytest tests/ -v
```
