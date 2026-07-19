# ⚒ Forge Router — Multi-LLM Orchestration Engine

A terminal-first AI assistant that routes prompts across **12 providers** with intent-based fallback chains, native image generation, a macOS preview window that renders Mermaid/Graphviz/PlantUML/D2, and persistent conversation memory with RAG retrieval.

**v0.5.1** — Phase 1 gateway MVP plus visual-routing upgrades: `forge_core` extracted, Anthropic-compatible gateway shipped, `visual` intent added, `openai_image` added for real image generation, and the preview now auto-opens for diagrams/media and includes a copy button. See [`docs/ENTERPRISE-GATEWAY-EVALUATION.md`](docs/ENTERPRISE-GATEWAY-EVALUATION.md).

---

## Architecture

```mermaid
graph TD
    User([Developer / AI Agent])
    CLI[forge CLI<br/>chat · ask · status · doctor]
    Chat[ForgeChat REPL<br/>prompt-toolkit · Rich<br/>/file /repo /write /run]
    Router[RouterEngine<br/>intent classify → fallback chain<br/>60s wall-clock cap]

    subgraph Providers [12 Providers]
        P0[Antigravity — Gemini Flash via agy CLI]
        P1[Cerebras — gpt-oss-120b]
        P2[Groq — gpt-oss-120B / LLaMA 3.3 70B]
        P3[Hermes — Groq backend]
        P4[Mistral — mistral-small]
        P5[Claude — Anthropic]
        P6[Codex — Responses API]
        P7[OpenRouter — R1 / Qwen / LLaMA]
        P8[Copilot — GitHub CLI]
        P9[OpenAI — GPT-4o]
        P10[OpenAI Image — gpt-image-1]
        P11[Ollama — Local CPU fallback]
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
| `visual` | 45s | image/photo prompts: openai_image → claude → openai → codex → openrouter → mistral → ollama; diagram prompts: claude → codex → openai → openrouter → mistral → groq → cerebras → ollama |
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

## Local-File Bridge

Cloud LLMs can't touch your filesystem — forge bridges that. Mention any real file or directory path in a prompt and forge reads it locally, injects the contents into the provider call, and the LLM answers as if it read the file itself:

```
Forge ❯ Can you review /Users/vikash/Documents/Projects/saturs/app.py?
◈ Auto-loaded /Users/vikash/Documents/Projects/saturs/app.py — 4,213 chars
  forge read it locally — the LLM now sees its contents in every call.
```

Works with files and whole directories (loaded as a repo tree), skips binaries, caps at 120KB/file, and stays loaded for the whole session across provider failovers. Explicit `/file` and `/repo` commands still work for fine control.

### Adaptive context fitting (per-provider input budgets)

Providers have wildly different input limits — Groq's free tier allows 12K tokens/minute while Claude takes 200K tokens. Instead of sending one giant prompt to everyone (and getting 413s from tight tiers), the router **fits the context to each provider individually**: file/repo sections are scored for relevance against your question and the best ones are kept within that provider's budget.

| Provider | Budget (chars ≈ tokens/4) | Constraint |
|---|---|---|
| claude | 200,000 | subscription CLI, arg-length bound |
| openai / codex | 300,000 | 128K+ token windows |
| antigravity | 200,000 | Gemini Flash 1M ctx, CLI arg-length bound |
| mistral / openrouter | 100,000 | 32K-token windows |
| copilot | 60,000 | CLI arg-length bound |
| cerebras | 48,000 | free-tier per-minute limits |
| hermes | 32,000 | free-tier TPM 12,000 |
| groq | 24,000 | gpt-oss-120b free-tier TPM 8,000 |
| ollama | 6,000 | num_ctx=2048 on CPU |

So a 230K-char repo goes to Claude in full, while Groq receives a relevance-selected 32K slice — and both answer from your local files. A `[Context auto-trimmed…]` note tells the model (and you, in logs) when trimming happened.

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
**Auto-open:** fires automatically when a response contains mermaid diagrams, images, SVG, or media
**Copy:** header button copies selected text or the full current preview output
**Diagram renderers:** Mermaid direct, Graphviz via Viz.js, PlantUML/D2 via Kroki, SVG inline
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

### Credentials — single source of truth

All API keys load from **`/Users/vikash/Documents/Projects/credentials/.env`** (falling back to a local `.env`). Parsed by `forge_core/config/settings.py` — keys are read once at startup and never logged or committed. How each of the 12 providers authenticate:

| Provider | Credential | Source |
|---|---|---|
| `groq`, `hermes` + quality judge | `GROQ_API_KEY` (or `GROQ_API_KEY_2`) | credentials/.env |
| `cerebras` | `CEREBRAS_API_KEY` | credentials/.env (cloud.cerebras.ai free tier) |
| `mistral` | `MISTRAL_API_KEY` | credentials/.env (console.mistral.ai free tier) |
| `claude` | **Claude Code CLI (paid subscription)** — `CLAUDE_CODE_OAUTH_TOKEN` optional; `ANTHROPIC_API_KEY` only as prepaid-API fallback | claude CLI OAuth |
| `openai` | `OPENAI_API_KEY` | credentials/.env |
| `codex` | `CODEX_API_KEY` (falls back to `OPENAI_API_KEY`) | credentials/.env |
| `openrouter` | `OPENROUTER_API_KEY` | credentials/.env |
| `copilot` | GitHub Copilot CLI login (`GITHUB_TOKEN`) | copilot CLI OAuth + credentials/.env |
| `openai_image` | `OPENAI_API_KEY` (falls back to `CODEX_API_KEY`) | credentials/.env |
| `antigravity` | none — `agy` CLI uses local OAuth | no key needed |
| `ollama` | none — local inference | no key needed |

Verify everything with `forge doctor`.

### Runtime data — single home at `~/.forge/`

```
~/.forge/
├── kb/               # FAISS + SQLite knowledge base (RAG memory)
├── generated/        # images created by openai_image (gpt-image-1)
├── repo-memory/      # /repo session summaries for cross-session recall
├── logs/             # observability.jsonl — quality judge scores
├── results.md        # last preview content
└── preview_state.json
```

Nothing is written into the repo or your CWD at runtime.

---

## Usage

```bash
forge                 # interactive chat (default)
forge chat --model groq
forge chat --preview  # open preview window immediately
forge ask "Explain Qdrant vs FAISS for hybrid search"
forge ask "Generate a product icon for forge-router"
forge status          # provider health (all 12)
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
| `/image <path>` | Attach image input for Vision |
| `/stats` `/kb` | Session stats + memory KB info |
| `/status` `/models` | Provider health check |
| `/clear` `/history` `/help` | Housekeeping |
| `exit` / `quit` / `bye` / `q` | Exit |

---

## Project Structure

Since v0.3.0 the engine lives in **`forge_core`** — an embeddable package with zero CLI/UI imports (enforced by test), so the CLI today and the HTTP gateway in Phase 1 drive the identical engine:

```
forge_core/                 # ── the embeddable engine (gateway-ready) ──
├── router/
│   ├── engine.py           # RouterEngine, RoutingContext, intent chains
│   └── observability.py    # Async LLM quality judge
├── providers/              # 12 provider adapters (all extend BaseProvider)
├── memory/
│   ├── knowledge_base.py   # FAISS + SQLite KB, auto-consolidation
│   └── embedder.py         # Ollama nomic-embed-text wrapper
└── config/
    └── settings.py         # pydantic-settings, credential loading

forge/                      # ── the CLI client ──
├── cli.py                  # Typer entry point (+ `gateway serve/keys/top`)
├── chat.py                 # ForgeChat REPL — context, preview, /write /run,
│                           #   local-file bridge (auto-loads paths in prompts)
└── ui/
    ├── console.py          # Rich terminal output
    ├── preview_server.py   # HTTP server + ForgePreview singleton
    └── preview_window.py   # pywebview WKWebView subprocess

forge_gateway/              # ── the HTTP gateway (Phase 1 MVP) ──
├── app.py                  # FastAPI create_app() — Anthropic /v1/messages, auth, metering
├── store.py                # virtual keys (SHA-256) + usage — SQLite ~/.forge/gateway.db
└── compress.py             # optional headroom SmartCrusher pass (degrades gracefully)
```

---

## Roadmap — Enterprise AI Gateway

Forge is evolving from a CLI router into a data-plane/control-plane AI gateway (virtual keys, OpenAI/Anthropic-compatible endpoints, cost metering, governance) while keeping this chat experience as its first client.

| Phase | Deliverable | Status |
|---|---|---|
| 0 — Extraction | `forge-core` package (router + providers, zero CLI imports) | ✅ done |
| 1 — Gateway MVP | FastAPI `/v1/chat/completions` + `/v1/messages`, virtual keys, cost metering | ⏳ in progress — `/v1/messages` + keys + metering shipped |
| 2 — Governance | Teams, RBAC, budgets, dashboards, audit log | planned |
| 3 — Intelligence | Guardrails, semantic cache, judge-informed routing, MCP registry | planned |
| 4 — Enterprise | SSO/SCIM, Helm/HA, compliance tooling | planned |

Full architecture: [`docs/ENTERPRISE-GATEWAY-EVALUATION.md`](docs/ENTERPRISE-GATEWAY-EVALUATION.md)

### Gateway (Phase 1, current state)

`forge_gateway/` is a FastAPI service that puts the router behind an
Anthropic-compatible HTTP endpoint, so any Anthropic-SDK client (Claude Code,
Cursor) can route through Forge with a virtual key instead of touching provider
keys directly.

```bash
forge gateway keys create my-key         # prints an fk-... key once
forge gateway serve --port 8099          # start the gateway
forge gateway top                        # per-key usage (reported when available, else estimated)
forge chat                               # interactive REPL
# inside chat:
/usage                                   # current session token usage
/usage total                             # aggregate from ~/.forge/session-usage.jsonl

# point a client at it:
ANTHROPIC_BASE_URL=http://127.0.0.1:8099 ANTHROPIC_API_KEY=fk-... claude
```

**Shipped:** `POST /v1/messages` (non-streaming), virtual keys (SHA-256 hashed,
per-key model allow-lists), per-request usage metering into
`~/.forge/gateway.db`, `/health`, and the shared `forge_core` router that now
supports a dedicated `visual` intent plus `openai_image` for real image output.
Requests route through the full intent router to the cheapest healthy provider
— so answers come from Forge's provider chain (Groq/Cerebras/…), **not** from
Anthropic.

**Not yet:** streaming (SSE), `POST /v1/chat/completions` (OpenAI), `GET /v1/models`,
budgets/quotas, and a full usage dashboard. Gateway metering now prefers provider-reported
counts when the backend returns them and falls back to a ~4-chars/token estimate otherwise.

---

**Author:** Vikash Jaiswal · vikashjaiswal.486@gmail.com — *Automating the future of AI Operations.*
