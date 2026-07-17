import os
import re
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger(__name__)

SHARED_ENV_PATH = Path("/Users/vikash/Documents/Projects/credentials/.env")
PROJECT_ENV_PATH = Path(".env")

def _load_clean_env(path: Path, override: bool = False) -> None:
    """Parse .env file skipping shell commands; inject valid KEY=VALUE into os.environ.

    override=True makes the file win over values already in the environment —
    the shared credentials file is the source of truth, and .zshrc exports
    stale copies of it into every shell at startup, which would otherwise
    shadow freshly edited keys until the terminal is reopened."""
    if not path.exists():
        return
    pattern = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = pattern.match(line)
            if m:
                key, val = m.group(1), m.group(2).strip('"').strip("'")
                if val and (override or not os.environ.get(key)):
                    os.environ[key] = val

_load_clean_env(SHARED_ENV_PATH, override=True)   # credentials/.env is authoritative
_load_clean_env(PROJECT_ENV_PATH)                 # local .env only fills gaps

# Alias: GROQ_API_KEY_2 → GROQ_API_KEY if not already set
if not os.environ.get("GROQ_API_KEY"):
    for k in ("GROQ_API_KEY_2", "GROQ_API_KEY_1"):
        if os.environ.get(k):
            os.environ["GROQ_API_KEY"] = os.environ[k]
            break

# Alias: CLAUDE_API_KEY → ANTHROPIC_API_KEY
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("CLAUDE_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]

logger.info("Env loaded from: %s", SHARED_ENV_PATH if SHARED_ENV_PATH.exists() else PROJECT_ENV_PATH)

class Settings(BaseSettings):
    # Groq
    groq_api_key: Optional[str] = None

    # Cerebras — wafer-scale chip, rivals Groq in speed, free ~100K tokens/day
    cerebras_api_key: Optional[str] = None

    # Mistral AI — mistral-small-latest is free (no quota cap)
    mistral_api_key: Optional[str] = None

    # OpenRouter — aggregates 200+ models via single key
    openrouter_api_key: Optional[str] = None

    # GitHub (Copilot CLI auth)
    github_token: Optional[str] = None

    # OpenAI / Codex
    openai_api_key: Optional[str] = None
    codex_api_key: Optional[str] = None
    codex_api_url: str = "https://api.openai.com/v1/responses"
    codex_model: str = "gpt-5.1-codex-mini"   # codex-mini-latest was retired; key verified to have gpt-5.x catalog

    # Anthropic — API key (prepaid console credits) is optional fallback;
    # primary claude backend is the Claude Code CLI (paid subscription)
    anthropic_api_key: Optional[str] = None
    claude_code_oauth_token: Optional[str] = None

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # App Settings
    debug: bool = False
    timeout: int = 30

    model_config = SettingsConfigDict(
        extra="ignore",
    )

settings = Settings()
