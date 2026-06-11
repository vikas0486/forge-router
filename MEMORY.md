# Forge Router Configuration

## Project Structure
- `forge/`: Main package
  - `cli.py`: Typer CLI entry point
  - `chat.py`: Interactive chat implementation
  - `router/`: Routing engine and fallback logic
  - `providers/`: LLM provider implementations
  - `config/`: Settings and provider configuration
  - `ui/`: Terminal UI helpers (Rich)
- `tests/`: Pytest suite

## Credential Source
Primary `.env` location: `/Users/vikash/Documents/Projects/credentials/.env`

## Fallback Order
1. Gemini
2. Groq
3. Claude Code
4. Codex
5. Copilot
6. OpenAI
7. Ollama (Final Fallback)
