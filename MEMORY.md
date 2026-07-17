# Forge Router Configuration

## Project Structure
- `forge/`: Main package
  - `cli.py`: Typer CLI entry point
  - `chat.py`: Interactive chat implementation
  - `router/`: Routing engine and fallback logic
  - `providers/`: LLM provider implementations (9 active)
  - `config/`: Settings and provider configuration
  - `ui/`: Terminal UI helpers (Rich)
- `tests/`: Pytest suite

## Credential Source
Primary `.env` location: `/Users/vikash/Documents/Projects/credentials/.env`

## Active Providers (in priority order)
1. Antigravity (`agy` CLI — Gemini Flash, no API key needed)
2. Groq (LLaMA 3.3 70B)
3. Hermes (Groq backend or local Ollama)
4. Sakana (fugu-ultra — paid subscription required)
5. Claude (Anthropic)
6. Copilot (GitHub Copilot CLI)
7. OpenAI (GPT-4o)
8. Codex (gpt-5-codex via Responses API)
9. Ollama (local, final fallback)

## Notes
- Gemini provider removed — Antigravity (`agy`) is the active Gemini replacement
- Wall-clock timeout: 60s per provider — router switches on breach regardless of intent timeout
- Sakana has no local fallback — if subscription invalid, fails fast (~0.7s) and routes on
