import os
import re
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger(__name__)

SHARED_ENV_PATH = Path("/Users/vikash/Documents/Projects/credentials/.env")
PROJECT_ENV_PATH = Path(".env")

def _load_clean_env(path: Path) -> None:
    """Parse .env file skipping shell commands; inject valid KEY=VALUE into os.environ."""
    if not path.exists():
        return
    pattern = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = pattern.match(line)
            if m:
                key, val = m.group(1), m.group(2).strip('"').strip("'")
                if val and key not in os.environ:
                    os.environ[key] = val

_load_clean_env(SHARED_ENV_PATH)
_load_clean_env(PROJECT_ENV_PATH)

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
    # Gemini
    gemini_api_key: Optional[str] = None
    
    # Antigravity
    antigravity_api_key: Optional[str] = None
    
    # Groq
    groq_api_key: Optional[str] = None

    # Sakana.ai
    sakana_api_key: Optional[str] = None

    # GitHub (Claude Code, Codex, Copilot)
    github_token: Optional[str] = None
    forge_read_token: Optional[str] = None
    
    # OpenAI
    openai_api_key: Optional[str] = None

    # Anthropic
    anthropic_api_key: Optional[str] = None

    # Perplexity (Sonar)
    perplexity_api_key: Optional[str] = None
    
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

