# ⚒ Forge Router — Multi-LLM Orchestration Engine

A terminal-first AI assistant that routes prompts across **11 LLM providers** with intent-based fallback chains, renders responses in a native macOS preview window, and maintains persistent conversation memory with RAG retrieval.

**v0.2.0** — last CLI-only release. Next: evolution into an enterprise AI gateway — see [`docs/ENTERPRISE-GATEWAY-EVALUATION.md`](docs/ENTERPRISE-GATEWAY-EVALUATION.md).

---

## Architecture

```mermaid
graph TD
    User([Developer / AI Agent])
    CLI[forge CLI<br/>chat · ask · status · doctor]
    Chat[ForgeChat REPL<br/>prompt-toolkit · Rich<br/>/file /repo /write /run]
    Router[RouterEngine<br/>intent classify → fallback chain<br/>60s wall-clock cap]

    subgraph Providers [11 LLM Providers]
        P0[Antigravity — Gemini Flash via agy CLI]
        P1[Cerebras — gpt-oss-120b]
        P2[Groq — LLaMA 3.3 70B]
        P3[Hermes — Groq backend]
        P4[Mistral — mistral-small]
        P5[Claude — Anthropic]
        P6[Codex — Responses API]
        P7[OpenRouter — R1 / Qwen / LLaMA]
        P8[Copilot — GitHub CLI]
        P9[OpenAI — GPT-4o]
        P10[Ollama — Local CPU fallback]
    end

    subgraph Memory [Knowledge Base]
        KB[FAISS IndexFlatIP<br/>768-dim cosine]
        DB[(SQLite<br/>interactions · memories)]
        EMB[nomic-embed-text<br/>via Ollama]
    end

    subgraph Preview [Live Preview]
        HTTP[HTTP Server :7654<br/>one per session]
        WK[WKWebView Window<br/>pywebview subprocess]
        HTML[Mermaid · Marked · hljs<br/>dark theme · 800ms poll]
    end

    OBS[Observability<br/>async LLM quality judge<br/>per-provider scores]

    User --> CLI --> Chat --> Router
    Router --> P0 & P1 & P2 & P3 & P4 & P5
    Router --> P6 & P7 & P8 & P9 & P10
    Router --> KB
    KB --> DB
    KB --> EMB
    Chat --> HTTP --> WK --> HTML
    Router --> OBS
```

---

## Intent Routing

Prompts are classified in under 1ms (regex), then routed through the optimal provider chain. Any provider exceeding the **60s wall-clock cap** is cancelled and the router moves on.

| Intent | Timeout | Provider Order |
|---|---|---|
| `chat` | 15s | groq → cerebras → antigravity → claude → mistral → openai → hermes → openrouter → ollama |
| `summarization` | 20s | antigravity → groq → cerebras → claude → mistral → openrouter → openai → ollama |
| `code` | 30s | codex → claude → hermes → openrouter → mistral → openai → groq → cerebras → ollama |
| `reasoning` | 45s | hermes → claude → openrouter → mistral → openai → groq → cerebras → antigravity → ollama |
| `agentic` | 60s | claude → openai → hermes → openrouter → groq → cerebras → mistral → antigravity → ollama |

Unhealthy providers are skipped automatically. Conversation history, loaded file/repo context, and RAG memories all transfer intact across fallbacks — every provider in the chain receives the identical assembled prompt.

```mermaid
sequenceDiagram
    participant U as User prompt
    participant R as RouterEngine
    participant A as Provider A
    participant B as Provider B
    participant J as Quality Judge (async)

    U->>R: prompt
    R->>R: classify_intent() <1ms
    R->>R: retrieve RAG memories (if KB warm)
    R->>A: generate(context + history + prompt)
    A-->>R: timeout / error
    R->>B: generate(identical assembled prompt)
    B-->>U: response (streamed to terminal + preview)
    R--)J: score(prompt, response, provider)
    J--)R: quality 1-10 → logged, feeds future routing
```

---

## Agentic File Operations

The core workflow: load a repo, ask any LLM to write/fix code, save it, run it, iterate — without leaving forge.

```
/repo /path/to/project      # inject entire repo into every LLM call
"Write a FastAPI endpoint"
/write src/api/users.py     # saves largest code block → auto-loads back into context
/run python src/api/users.py  # output injected into conversation history
"Fix the error above"       # next LLM (even after failover) sees the error
```

---

## Preview Window

```mermaid
sequenceDiagram
    participant T as Terminal (forge chat)
    participant S as HTTP Server :7654
    participant W as WKWebView Window

    T->>S: _ensure_server() — bind once per session
    T->>W: subprocess Popen (preview_window.py)
    W->>S: GET / (load HTML shell)
    loop every 800ms
        W->>S: GET /state (JSON)
        S-->>W: content + provider + model + msg_count
        W->>W: render markdown + mermaid + hljs
    end
    T->>S: preview.write(new_content)
    T->>W: terminate() on /p toggle OFF
    T->>S: server.shutdown() on forge exit
```

**Toggle:** `/p`, `/preview`, or `Ctrl+P`
**Auto-open:** fires automatically when a response contains mermaid diagrams, images, or media
**Restore on open:** last response shown immediately — no blank window

---

## Knowledge Base (RAG)

```mermaid
graph LR
    Prompt --> Embed[nomic-embed-text<br/>768-dim]
    Embed --> FAISS[FAISS IndexFlatIP<br/>cosine similarity]
    FAISS --> Top4[Top-4 memories<br/>threshold 0.55]
    Top4 --> CtxBlock[Context block<br/>injected into prompt]
    CtxBlock --> LLM[LLM Provider]

    LLM --> Response
    Response --> Score[Observability<br/>quality score]
    Score --> SQLite[(SQLite<br/>interactions)]
    SQLite --> Consolidate[Auto-consolidate<br/>every 10 interactions]
    Consolidate --> Facts[Extract facts<br/>via Groq / local LLM]
    Facts --> Embed
```

**Cold-start safe:** retrieval is skipped when the index is empty — no embed cost on first run.

---

## Installation

```bash
git clone https://github.com/vikas0486/forge-router.git
cd forge-router

# pipx (recommended — global `forge` command)
pipx install .

# or with uv
uv sync && uv pip install -e .
```

Credentials load from `/Users/vikash/Documents/Projects/credentials/.env` (or a local `.env`):

```env
GROQ_API_KEY=...        # groq + hermes + quality judge
CEREBRAS_API_KEY=...    # cloud.cerebras.ai (free tier)
MISTRAL_API_KEY=...     # console.mistral.ai (free tier)
ANTHROPIC_API_KEY=...   # claude
OPENAI_API_KEY=...      # openai + codex fallback
CODEX_API_KEY=...       # codex (preferred)
OPENROUTER_API_KEY=...  # openrouter.ai
GITHUB_TOKEN=...        # copilot CLI
```

Antigravity (`agy` CLI) and Ollama need no API keys.

---

## Usage

```bash
forge                 # interactive chat (default)
forge chat --model groq
forge chat --preview  # open preview window immediately
forge ask "Explain Qdrant vs FAISS for hybrid search"
forge status          # provider health (all 11)
forge doctor          # diagnose keys + tools + health
```

### In-chat commands

| Command | Action |
|---|---|
| `/file <path>` | Load a file into session context |
| `/repo <path>` | Load an entire repo into session context |
| `/context` | Show loaded files — `/context clear` to reset |
| `/write <path>` | Save last response (or largest code block) to file |
| `/run <command>` | Run shell command, inject output as context |
| `/p` `/preview` `Ctrl+P` | Toggle WKWebView preview window |
| `/model <name\|auto>` | Lock to a provider / resume auto-routing |
| `/image <path>` | Attach image for Vision |
| `/stats` `/kb` | Session stats + memory KB info |
| `/status` `/models` | Provider health check |
| `/clear` `/history` `/help` | Housekeeping |
| `exit` / `quit` / `bye` / `q` | Exit |

---

## Project Structure

```
forge/
├── cli.py                  # Typer entry point
├── chat.py                 # ForgeChat REPL — context, preview, /write /run
├── router/
│   ├── engine.py           # RouterEngine, RoutingContext, intent chains
│   └── observability.py    # Async LLM quality judge
├── providers/              # 11 provider adapters (all extend BaseProvider)
├── memory/
│   ├── knowledge_base.py   # FAISS + SQLite KB, auto-consolidation
│   └── embedder.py         # Ollama nomic-embed-text wrapper
├── ui/
│   ├── console.py          # Rich terminal output
│   ├── preview_server.py   # HTTP server + ForgePreview singleton
│   └── preview_window.py   # pywebview WKWebView subprocess
└── config/
    └── settings.py         # pydantic-settings, credential loading
```

---

## Roadmap — Enterprise AI Gateway

Forge is evolving from a CLI router into a data-plane/control-plane AI gateway (virtual keys, OpenAI/Anthropic-compatible endpoints, cost metering, governance) while keeping this chat experience as its first client.

| Phase | Deliverable |
|---|---|
| 0 — Extraction | `forge-core` package (router + providers, zero CLI imports) |
| 1 — Gateway MVP | FastAPI `/v1/chat/completions` + `/v1/messages`, virtual keys, cost metering |
| 2 — Governance | Teams, RBAC, budgets, dashboards, audit log |
| 3 — Intelligence | Guardrails, semantic cache, judge-informed routing, MCP registry |
| 4 — Enterprise | SSO/SCIM, Helm/HA, compliance tooling |

Full architecture: [`docs/ENTERPRISE-GATEWAY-EVALUATION.md`](docs/ENTERPRISE-GATEWAY-EVALUATION.md)

---

**Author:** Vikash Jaiswal · vikashjaiswal.486@gmail.com — *Automating the future of AI Operations.*
