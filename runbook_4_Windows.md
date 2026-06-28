# ⚒️ Forge Router — Windows Runbook

A step-by-step guide to install, configure, and run **Forge Router** on Windows 10/11.
Follow top-to-bottom the first time; after that, jump to [Daily use](#5-daily-use).

> **TL;DR (already set up?)**
> ```powershell
> cd "D:\AI Projects\forge-router"
> $env:PYTHONUTF8 = "1"
> .\.venv\Scripts\python.exe -m forge.cli chat
> ```

---

## 0. What you need

| Requirement | Why | Check |
|---|---|---|
| **Python 3.13+** | App targets `requires-python >=3.13` | `python --version` |
| **PowerShell 7** (recommended) | Modern shell, UTF-8 friendly | `pwsh --version` |
| **Git** | Clone the repo | `git --version` |
| API keys *(optional)* | For live answers from cloud providers | see [Step 3](#3-configure-credentials) |
| **Ollama** *(optional)* | Fully offline / local model + RAG memory | https://ollama.com |

> ℹ️ The app **launches and routes without any keys**, but every provider will
> report `FAILED` until you add at least one credential (or run a local model).

---

## 1. Get the code

```powershell
# If you don't already have it:
git clone https://github.com/vikash/forge-router.git
cd forge-router
```

Already on disk? Just:

```powershell
cd "D:\AI Projects\forge-router"
```

---

## 2. Install (one time)

There is **no `uv` or global `forge` command** required. We use a local virtual
environment so dependencies stay isolated.

```powershell
cd "D:\AI Projects\forge-router"

# Create the virtual environment with Python 3.13
python -m venv .venv

# If `python` isn't on your PATH, use the full path, e.g.:
#   & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv

# Upgrade pip and install the project (editable) + all dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

This pulls in `typer`, `rich`, `prompt-toolkit`, `faiss-cpu`, `pywebview`, etc.
First install takes ~1–2 minutes.

**Verify the install:**

```powershell
.\.venv\Scripts\python.exe -c "import typer, rich, faiss, webview; print('deps OK')"
```

---

## 3. Configure credentials

Forge auto-loads a **`.env` file from the project folder** (`forge-router\.env`).

> ⚠️ **Known gotcha:** the app also tries a hardcoded path from the original
> author's Mac (`/Users/vikash/Documents/Projects/credentials/.env`). On Windows
> that simply doesn't exist and is ignored — **use the project `.env` instead.**

Create `forge-router\.env` and add whichever keys you have:

```env
# Cloud providers (add any you own — more keys = more providers available)
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GITHUB_TOKEN=your_github_token

# Local model (optional — only if you run Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

> 🔒 **Security:** `.env` is gitignored — **never commit real keys.** Each team
> member supplies their own. (For this workspace the single source of truth is
> `D:\AI Projects\credentials.md`, synced via `sync-credentials.ps1`.)

**Fully offline option (no API keys):** install [Ollama](https://ollama.com),
then pull models:

```powershell
ollama pull llama3
ollama pull nomic-embed-text   # enables the RAG memory / knowledge base
```

---

## 4. ⚡ The UTF-8 fix (REQUIRED on Windows)

Forge's UI uses emoji (⚒️ 🛠️). The default Windows console code page (cp1252)
**crashes** with:

```
Fatal Error: 'charmap' codec can't encode characters...
```

Set UTF-8 mode **before running any forge command**. Pick one:

**Per session (quickest):**
```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

**Permanent (recommended for the whole team):** set it once for your user:
```powershell
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
# Restart your terminal afterwards.
```

---

## 5. Daily use

Always run from the project folder with the venv's Python:

```powershell
cd "D:\AI Projects\forge-router"
$env:PYTHONUTF8 = "1"          # skip if you set it permanently in Step 4

# Interactive chat (main experience)
.\.venv\Scripts\python.exe -m forge.cli chat

# One-shot question
.\.venv\Scripts\python.exe -m forge.cli ask "Explain FAISS vs Qdrant"

# Force a specific provider
.\.venv\Scripts\python.exe -m forge.cli ask "hello" --model groq

# Open the live Mermaid/Markdown preview window
.\.venv\Scripts\python.exe -m forge.cli chat --preview

# Health of every provider
.\.venv\Scripts\python.exe -m forge.cli status

# Diagnose config / keys / tools  ← run this first if something is wrong
.\.venv\Scripts\python.exe -m forge.cli doctor
```

### In-chat commands

| Command | Action |
|---|---|
| `/p`, `/preview`, `Ctrl+P` | Toggle the preview window |
| `/model <name>` | Lock to a provider (`groq`, `claude`, …) |
| `/model auto` | Release lock, resume auto-routing |
| `/status` | Provider health |
| `/stats`, `/kb` | Session stats + memory info |
| `/clear` | Reset screen + conversation |
| `/help` | All commands |
| `exit` / `quit` / `bye` | Leave |

### Optional: a shorter command

To avoid typing the full venv path, activate the environment first:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python -m forge.cli chat
```

> If activation is blocked by execution policy, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `'charmap' codec can't encode…` | Console not UTF-8 | [Step 4](#4-the-utf-8-fix-required-on-windows) |
| `No module named 'typer'` | Using global Python, not the venv | Use `.\.venv\Scripts\python.exe …` |
| `python` not recognized | Python not on PATH | Use full path `…\Programs\Python\Python313\python.exe` |
| All providers `FAILED` in `doctor` | No keys / no local model | [Step 3](#3-configure-credentials) |
| `Credentials NOT found at /Users/vikash/…` | Harmless hardcoded Mac path | Ignore — use project `.env` |
| `antigravity timed out` | Needs local `agy` CLI (not installed) | Use another provider or Ollama |
| `[kb] retrieve failed: connection attempts failed` | Ollama not running | Start Ollama, or ignore (memory is optional) |
| `Activate.ps1 cannot be loaded` | PS execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

**First debugging step is always:**
```powershell
.\.venv\Scripts\python.exe -m forge.cli doctor
```

---

## 7. Run the tests (optional)

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

---

## Quick reference card

```powershell
# === FIRST TIME ===
cd "D:\AI Projects\forge-router"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
# create forge-router\.env with your API keys
[Environment]::SetEnvironmentVariable("PYTHONUTF8","1","User")   # then restart terminal

# === EVERY TIME ===
cd "D:\AI Projects\forge-router"
.\.venv\Scripts\python.exe -m forge.cli chat
```

---

*Maintainer note: keep this runbook in sync with `README.md`. Windows-specific
quirks (UTF-8, venv path, hardcoded Mac credentials path) live here so the cross-
platform README stays clean.*
