# ⚒ Forge Router — Multi-LLM Orchestration Engine

A terminal-first AI assistant that routes prompts across **10 LLM providers**, renders responses in a native macOS preview window, and maintains persistent conversation memory with RAG retrieval.

---

## Architecture

```mermaid
graph TD
    User([Developer / AI Agent])
    CLI[forge CLI<br/>chat · ask · status · doctor]
    Chat[ForgeChat REPL<br/>prompt-toolkit · Rich]
    Router[RouterEngine<br/>intent classify → fallback chain]

    subgraph Providers [10 LLM Providers]
        P1[Groq — LLaMA 3.3 70B]
        P2[Antigravity — Gemini Flash]
        P3[Claude — Anthropic]
        P4[OpenAI — GPT-4o]
        P5[Codex — Code specialist]
        P6[Hermes — Reasoning]
        P7[Gemini — Google]
        P8[Sakana AI]
        P9[Copilot — GitHub]
        P10[Ollama — Local / Offline]
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

    OBS[Observability<br/>per-provider quality scores]

    User --> CLI --> Chat --> Router
    Router --> P1 & P2 & P3 & P4 & P5
    Router --> P6 & P7 & P8 & P9 & P10
    Router --> KB
    KB --> DB
    KB --> EMB
    Chat --> HTTP --> WK --> HTML
    Router --> OBS
```

---

## Intent Routing

Prompts are classified in under 1ms (regex), then routed to the optimal provider chain:

| Intent | Timeout | Provider Order |
|---|---|---|
| `chat` | 15s | Groq → Antigravity → Claude → OpenAI → Hermes → Ollama |
| `summarization` | 20s | Antigravity → Groq → Claude → OpenAI → Ollama |
| `code` | 30s | Codex → Claude → Hermes → OpenAI → Groq → Ollama |
| `reasoning` | 45s | Hermes → Claude → OpenAI → Groq → Sakana → Antigravity → Ollama |
| `agentic` | 60s | Claude → OpenAI → Hermes → Groq → Antigravity → Ollama |

Unhealthy providers are skipped automatically. Context (conversation history) transfers intact across fallbacks.

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
**Auto-open:** fires automatically when response contains mermaid diagrams, images, or media
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

**Cold-start safe:** retrieval skipped when index is empty — no embed cost on first run.

---

## Installation

> 🪟 **On Windows?** Follow the **[Windows Runbook](runbook_4_Windows.md)** instead — it
> covers the venv setup, the required UTF-8 console fix, and Windows-specific gotchas
> step by step. Copy `.env.example` → `.env` and add your keys.

```bash
# Clone
git clone https://github.com/vikash/forge-router.git
cd forge-router

# Install (pipx recommended — gives a global forge command)
pipx install .

# Or with uv
uv sync && uv pip install -e .
```

Configure credentials in `~/.devo/credentials` or `.env` (copy `.env.example` to start):

```env
ANTIGRAVITY_API_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GITHUB_TOKEN=...
```

---

## Usage

```bash
# Interactive chat (recommended)
forge chat

# Force a provider
forge chat --model groq

# Open preview window immediately
forge chat --preview

# One-shot question
forge ask "Explain Qdrant vs FAISS for hybrid search"

# Provider health
forge status

# Diagnose env / keys / tools
forge doctor
```

### In-chat commands

| Command | Action |
|---|---|
| `/p` or `/preview` | Toggle WKWebView preview window |
| `Ctrl+P` | Same — keyboard shortcut |
| `/model <name>` | Lock to a provider |
| `/model auto` | Release lock, resume routing |
| `/image <path>` | Attach image for Vision |
| `/stats` `/kb` | Session stats + memory KB info |
| `/status` | Provider health check |
| `/clear` | Reset screen + conversation context |
| `/history` | Recent prompt history |
| `/help` | All commands |
| `exit` / `quit` / `bye` | Exit |

---

## Project Structure

```
forge/
├── cli.py                  # Typer entry point
├── chat.py                 # ForgeChat REPL — preview lifecycle, key bindings, history
├── router/
│   ├── engine.py           # RouterEngine, RoutingContext, intent classification
│   └── observability.py    # Quality scoring per provider
├── providers/              # 10 provider adapters (all extend BaseProvider)
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

## Roadmap — AI Gateway Governance

| Phase | Timeline | Deliverable |
|---|---|---|
| 0 — Foundation | Jun 28 – Jul 4 | DORA KPI baseline, observability hooks |
| 1 — Gateway Core | Jul 5 – Jul 18 | Rate limiter, circuit breaker, token budget, prompt injection detector |
| 2 — Qdrant + Privacy | Jul 19 – Aug 8 | Offline Qdrant (Docker), PII classifier, data sovereignty routing |
| 3 — Semantic Cache | Aug 9 – Aug 22 | ChromaDB embedded prototype, cache layer |
| 4 — Multi-Agent | Aug 23 – Sep 5 | Agent competition, QoS tiers |
| 5 — GPU Backends | Sep 6 – Sep 19 | High-performance inference server integration |

Full governance design: `AI_GATEWAY_GOVERNANCE.md` in the AI-Forge repo.

---

**Author:** Vikash Jaiswal — *Automating the future of AI Operations.*
